"""课程新安江单机引擎：显式状态、守恒产流、v2汇流及可选单位线。"""
from __future__ import annotations
import math
import numpy as np


def check_params(p):
    """检查外置参数物理范围与课程固定单位。"""
    required = 'K WUM WLM WDM C B IM SM EX KI KG CI CG U dt_h routing'.split()
    if any(k not in p for k in required):
        raise ValueError('缺少模型参数')
    if any(not math.isfinite(float(p[k])) for k in required if k != 'routing'):
        raise ValueError('参数必须有限')
    if any(p[k] <= 0 for k in ('WUM','WLM','WDM','SM','B','EX')):
        raise ValueError('容量和曲线指数必须为正')
    if p['K'] < 0 or not 0 <= p['C'] <= 1 or not 0 <= p['IM'] < 1:
        raise ValueError('蒸散发或不透水面积参数非法')
    if min(p['KI'],p['KG']) < 0 or p['KI']+p['KG'] > 1:
        raise ValueError('要求KI+KG≤1')
    if any(not 0 <= p[k] < 1 for k in ('CI','CG')):
        raise ValueError('消退系数必须在[0,1)')
    if p['U'] != 92.6 or p['dt_h'] != 6:
        raise ValueError('课程固定使用U=92.6、Δt=6h')
    if p['routing'] == 'v2':
        if not 0 <= p['CS'] < 1 or not 0 <= p['X'] <= .5 or p['KE'] <= 0:
            raise ValueError('v2汇流参数非法')
        if p['KE']*p['X'] > 3+1e-9 or p['KE']*(1-p['X']) < 3-1e-9:
            raise ValueError('马斯京根系数非负条件不成立')
    elif p['routing'] == 'uh':
        if 'UH' not in p:
            raise ValueError('当前数据包无UH；须外置提供真实单位线才能使用uh模式')
        uh = np.asarray(p['UH'],float)
        if uh.ndim != 1 or not len(uh) or not np.isfinite(uh).all() or (uh < 0).any() or not np.isclose(uh.sum(),p['U']):
            raise ValueError('UH单位为(m³/s)/mm，非负且总和必须为U=92.6')
    else:
        raise ValueError('routing只能为v2或uh')


def evapotranspire(P, EM, params, state):
    """透水区三层蒸散发；只扣除实际水耗，降雨净增量由产流模块处理。"""
    s = dict(state)
    ep = params['K']*EM
    eu = min(ep, s['WU']+P)
    shortage = ep-eu
    if s['WL'] >= params['C']*params['WLM']:
        el, ed = min(shortage*s['WL']/params['WLM'],s['WL']), 0.
    elif s['WL'] >= params['C']*shortage:
        el, ed = params['C']*shortage, 0.
    else:
        el = s['WL']
        ed = min(params['C']*shortage-el,s['WD'])
    s['WU'] -= max(eu-P,0.)
    s['WL'] -= el
    s['WD'] -= ed
    return eu+el+ed, s


def runoff(PE, params, state):
    """蓄水容量曲线产流，R为透水区平均深；返回R、FR及逐层补水后的状态。"""
    s = dict(state)
    if PE <= 0:
        return 0.,0.,s
    wm = sum(params[k] for k in ('WUM','WLM','WDM'))
    w = sum(s[k] for k in ('WU','WL','WD'))
    b = params['B']
    wmm = wm*(1+b)
    a = wmm*(1-max(0.,1-w/wm)**(1/(1+b)))
    r = PE-wm+w+wm*max(0.,1-(PE+a)/wmm)**(1+b)
    r = min(PE,max(0.,r))
    remaining = PE-r
    for key, capacity in zip(('WU','WL','WD'),('WUM','WLM','WDM')):
        fill = min(remaining,max(0.,params[capacity]-s[key]))
        s[key] += fill
        remaining -= fill
    return r,r/PE,s


def split_sources(R, FR, params, state):
    """数据包v2自由水曲线及分配规则；溢流显式计入RS，逐步守恒。"""
    s = dict(state)
    old = s['S']
    if R <= 0 or FR <= 0:
        return 0.,0.,0.,s
    sm, ex = params['SM'],params['EX']
    smm = sm*(1+ex)
    au = smm*(1-max(0.,1-old/sm)**(1/(1+ex)))
    rb = max(0.,FR*(R-sm+old+sm*max(0.,1-(R+au)/smm)**(1+ex)))
    ri, rg = params['KI']*old*FR, params['KG']*old*FR
    if ri+rg > rb:
        factor = rb/(ri+rg)
        ri,rg = ri*factor,rg*factor
    raw = old+R-rb
    s['S'] = min(sm,max(0.,raw))
    rs = max(0.,rb-ri-rg)+max(0.,raw-sm)
    assert abs(old+R-s['S']-rs-ri-rg) < 1e-7, '自由水不守恒'
    return rs,ri,rg,s


def route(RS, RI, RG, params, state):
    """一步汇流，返回流量和新状态；UH尾部、河道前时刻入出流均显式保存。"""
    s = dict(state)
    u = params['U']
    qi = params['CI']*s['QI']+(1-params['CI'])*u*RI
    qg = params['CG']*s['QG']+(1-params['CG'])*u*RG
    if params['routing'] == 'uh':
        uh = np.asarray(params['UH'])
        pending = np.asarray(s.get('UH_pending',np.zeros(len(uh))),float).copy()
        if pending.shape != uh.shape:
            raise ValueError('UH缓存维度错误')
        pending += RS*uh
        qs = float(pending[0])
        s['UH_pending'] = np.r_[pending[1:],0.].tolist()
        q = qs+qi+qg
    else:
        qs = params['CS']*s.get('QS',0.)+(1-params['CS'])*u*RS
        inflow = qs+qi+qg
        if 'channel_in' not in s:
            q = inflow  # 与数据包一致：首时刻出流=入流
        else:
            ke,x,dt = params['KE'],params['X'],params['dt_h']
            den = ke*(1-x)+dt/2
            q = ((dt/2-ke*x)*inflow+(dt/2+ke*x)*s['channel_in']+
                 (ke*(1-x)-dt/2)*s['channel_out'])/den
        s.update(channel_in=inflow,channel_out=q)
    s.update(QS=qs,QI=qi,QG=qg)
    return q,s


def simulate(inputs, params, state0):
    """模拟(P,EM)序列，参数和state0只读；返回过程及可继续运行的state_end。

    张力水按透水区口径存储，流域水量平衡使用(1-IM)W；
    不透水区先蒸发再直接产流，避免重复计入IM产流。
    初态超容截断量单独报告，不伪装成模拟时段内水量。
    """
    check_params(params)
    s = dict(state0)
    if any(k not in s for k in ('WU','WL','WD','S','QI','QG')):
        raise ValueError('初态缺失')
    if any(not math.isfinite(float(v)) or v < 0 for k,v in s.items() if k != 'UH_pending'):
        raise ValueError('状态必须为非负有限数')
    adjustment = {}
    for key,cap in zip(('WU','WL','WD','S'),('WUM','WLM','WDM','SM')):
        adjustment[key] = max(0.,s[key]-params[cap])
        s[key] = min(s[key],params[cap])
    rows = []
    f = 1-params['IM']
    for item in inputs:
        p,em = (item['P'],item['EM']) if isinstance(item,dict) else item
        if not math.isfinite(p+em) or min(p,em) < 0:
            raise ValueError('P、EM必须非负且有限')
        w0 = sum(s[k] for k in ('WU','WL','WD'))
        free0 = s['S']
        ep,s = evapotranspire(p,em,params,s)
        r,fr,s = runoff(max(0.,p-ep),params,s)
        rs,ri,rg,s = split_sources(r,fr,params,s)
        eim = min(p,params['K']*em)
        e = f*ep+params['IM']*eim
        total_r = f*r+params['IM']*(p-eim)
        w = sum(s[k] for k in ('WU','WL','WD'))
        balance = p-e-total_r-f*(w-w0)
        assert abs(balance) < 1e-7, f'张力水不守恒: {balance}'
        rs,ri,rg = f*rs+params['IM']*(p-eim),f*ri,f*rg
        full = p-e-rs-ri-rg-f*(w-w0+s['S']-free0)
        assert abs(full) < 1e-7, f'产流分配不守恒: {full}'
        q,s = route(rs,ri,rg,params,s)
        rows.append((q,e,total_r,f*w,f*s['S'],rs,ri,rg,balance,full))
    names = 'Q E R W S RS RI RG balance source_balance'.split()
    result = {key: np.asarray([r[i] for r in rows]) for i,key in enumerate(names)}
    result.update(state_end=s,initial_adjustment=adjustment)
    return result


def _paired(obs, sim):
    """统一检查评价序列，禁止缺测、空值及形状错配。"""
    a,b = np.asarray(obs,float),np.asarray(sim,float)
    if a.ndim != 1 or a.shape != b.shape or not len(a) or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('评价序列必须等长、非空、一维且有限')
    return a,b


def calc_dc(obs, sim):
    """DC=NSE；观测方差为零时拒绝给出误导性的指标。"""
    a,b = _paired(obs,sim)
    den = np.sum((a-a.mean())**2)
    if den == 0:
        raise ValueError('常量观测序列的DC未定义')
    return float(1-np.sum((a-b)**2)/den)


def calc_rmse(obs, sim):
    """均方根误差，单位m³/s。"""
    a,b = _paired(obs,sim)
    return float(np.sqrt(np.mean((a-b)**2)))


def calc_peak_relative_error(obs, sim):
    """有符号洪峰相对误差(%)，正值表示高估，重复峰取首次。"""
    a,b = _paired(obs,sim)
    if a.max() <= 0:
        raise ValueError('观测洪峰为零，相对误差未定义')
    return float((b.max()-a.max())/a.max()*100)


def calc_peak_time_error(obs, sim, dt_h=6):
    """有符号峰现时间差(h)，正值表示模拟峰偏晚，重复峰取首次。"""
    a,b = _paired(obs,sim)
    return float((np.argmax(b)-np.argmax(a))*dt_h)
