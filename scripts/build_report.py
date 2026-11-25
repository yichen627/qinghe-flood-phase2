"""根据已保存验收证据生成个人二期总结报告，使用python-docx。"""
from pathlib import Path
import json
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'docs'/'evidence'


def main():
    """按课程必做项组织报告，各小标题统一黑体，无参考文献章节。"""
    runs = json.loads((OUT/'acceptance.json').read_text(encoding='utf-8'))['runs']
    burst = json.loads((OUT/'burst-acceptance.json').read_text(encoding='utf-8'))
    ci = json.loads((OUT/'final-ci.json').read_text(encoding='utf-8'))
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.top_margin, sec.bottom_margin = Cm(2.1), Cm(2)
    sec.left_margin, sec.right_margin = Cm(2.3), Cm(2.3)
    for name in ('Normal','Title','Subtitle','Heading 1','Heading 2','Caption'):
        style = doc.styles[name]
        style.font.name = 'Times New Roman'
        style.font.color.rgb = RGBColor(0,0,0)
        style.font.italic = False
        fonts = style.element.get_or_add_rPr().rFonts
        fonts.set(qn('w:eastAsia'),'宋体')
        style.paragraph_format.widow_control = True
    normal = doc.styles['Normal']
    normal.font.size = Pt(11)
    normal.paragraph_format.line_spacing = 1.3
    normal.paragraph_format.space_after = Pt(7)
    for name, size in [('Title',25),('Subtitle',16),('Heading 1',17),('Heading 2',12)]:
        style = doc.styles[name]
        style.font.size = Pt(size)
        style.paragraph_format.space_before = Pt(10)
        style.paragraph_format.space_after = Pt(9)
        if name.startswith('Heading'):
            style.font.bold = True
            style.font.name = 'SimHei'
            fonts = style.element.get_or_add_rPr().rFonts
            for attr in ('ascii','hAnsi','cs','eastAsia'):
                fonts.set(qn('w:'+attr), '黑体' if attr=='eastAsia' else 'SimHei')
            for attr in ('asciiTheme','hAnsiTheme','eastAsiaTheme','cstheme'):
                fonts.attrib.pop(qn('w:'+attr),None)
    for element in doc.styles.element.iter(qn('w:pBdr')):
        element.getparent().remove(element)
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'),'PAGE')
    footer._p.append(field)
    doc.core_properties.title = '青河流域洪水预报系统二期总结报告'
    doc.core_properties.author = '陈一'
    doc.core_properties.subject = '领域软件工程大作业'

    def p(text):
        """添加带首行缩进的正文。"""
        para = doc.add_paragraph(text)
        para.paragraph_format.first_line_indent = Cm(.74)
        return para

    def h(text):
        """添加黑体二级标题。"""
        return doc.add_heading(text,2)

    def page(title):
        """新页承载一个完整报告主题。"""
        doc.add_page_break()
        doc.add_heading(title,1)

    def table(headers, rows):
        """添加重复表头和不拆行的轻灰边框表格。"""
        t = doc.add_table(rows=1,cols=len(headers))
        for cell, text in zip(t.rows[0].cells,headers):
            cell.text = str(text)
        for values in rows:
            for cell,text in zip(t.add_row().cells,values):
                cell.text = str(text)
        for index,row in enumerate(t.rows):
            row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
            for cell in row.cells:
                props = cell._tc.get_or_add_tcPr()
                borders = OxmlElement('w:tcBorders')
                for edge in ('top','bottom','left','right'):
                    e = OxmlElement('w:'+edge)
                    for k,v in [('val','single'),('sz','4'),('color','D9D9D9')]:
                        e.set(qn('w:'+k),v)
                    borders.append(e)
                props.append(borders)
                if index==0:
                    shade = OxmlElement('w:shd')
                    shade.set(qn('w:fill'),'E9EEF2')
                    props.append(shade)
                for para in cell.paragraphs:
                    para.paragraph_format.space_before = Pt(5)
                    para.paragraph_format.space_after = Pt(5)
                    para.paragraph_format.line_spacing = 1.1
                    for run in para.runs:
                        run.font.size = Pt(9)
                        run.font.bold = index==0
        t.rows[0]._tr.get_or_add_trPr().append(OxmlElement('w:tblHeader'))
        return t

    # 第一页封面。
    doc.add_paragraph().paragraph_format.space_after = Pt(35)
    for text,style in [('河海大学','Subtitle'),('领域软件工程大作业','Subtitle'),
                       ('青河流域洪水预报系统','Title'),('二期总结报告','Subtitle')]:
        para = doc.add_paragraph(text,style)
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph().paragraph_format.space_after = Pt(30)
    for text in ['学院  计算机与软件学院','专业  软件工程','班级  24级1班',
                 '姓名  陈一','学号  2406050103','完成形式  个人独立完成','日期  2026年11月25日']:
        para = doc.add_paragraph(text)
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER

    page('一 项目目标与需求范围')
    p('本项目在一期三水源新安江模型引擎基础上，完成从数据入库、预报计算到产品复核签发的单机业务系统。二期保留一期已验证的模型与冻结参数，将开发重点转向输入质量、服务契约、任务持久化、版本追溯与部署验收。项目由本人以个人形式完成，版本为1.0.0。')
    h('1 必做功能与用例')
    table(['必做项','交付内容','关联用例'],[
        ['M1 数据与质控','原始CSV、逐时段数据和质控问题入库','UC1 UC5'],
        ['M2 预报流水线','手动或计划起报，HTTP调用独立模型','UC1'],
        ['M3 结果管理','历史查询、过程线、指标、误差导出','UC3'],
        ['M4 方案管理','不可变参数版本、绑定、灰度与回滚','UC4'],
        ['M5 运行留痕','输入与状态快照、版本摘要、操作审计','UC2 UC3']])
    h('2 交付边界')
    p('操作入口采用FastAPI交互式文档，部署为API、模型、worker、scheduler四个容器，SQLite承担单机持久化。通知进入本地值班收件箱；未开发专门Web工作台、集合预报及外部微信或邮件通道。产品签发保存角色、时间与内容摘要，属于业务记录，不是证书数字签名。')
    h('3 验收原则')
    p('验收同时检查算法结果和工程行为：四场黄金过程线一致、检验场DC不低于0.85、错误输入被阻断、未签发产品不得发布、快照回放可复现，以及服务重启后任务和计划仍可追踪。单次预报180秒与自动质控通知5分钟为课程目标，测量结果仅代表本机小数据窗口。')

    page('二 架构设计与数据组织')
    h('1 分层和依赖方向')
    p('接口层负责请求结构、角色授权和HTTP响应；应用服务层编排入库、起报、回放和产品状态流转；仓储与模型适配层分别封装SQLite事务和模型HTTP调用。模型服务只接收输入、参数及初态，不依赖业务数据库。依赖沿接口到应用再到适配器单向流动。')
    table(['进程','主要职责','失效时的可见行为'],[
        ['api','数据与任务API、产品和版本治理','健康检查失败，客户端无法提交'],
        ['model','调用纯函数simulate并返回过程线','HTTP超时或异常转为任务FAILED'],
        ['worker','短事务领取任务、调用模型、保存结果','心跳滞后，超租约任务失败留痕'],
        ['scheduler','计划起报、质控巡检、通知投递','心跳滞后，计划持久化待恢复']])
    h('2 主要数据实体')
    p('events保存原始CSV、指纹、该场初态和质控结果；forecasts保存任务状态、完整快照与输出。parameter_sets与model_versions构成版本注册表，schemes绑定参数与算法，routing记录活动方案和灰度比例。products保存不可变产品内容及复核签发信息。schedules、schedule_runs、alerts、notification_outbox、inbox和audit分别记录自动业务及审计。')
    h('3 一致性与可追溯性')
    p('数据库启用外键、WAL和参数绑定SQL。HTTP模型计算期间不持有写事务，避免长事务阻塞。创建计划任务、触发记录和推进计划时间在同一事务内完成；通知实际入箱和DELIVERED状态也在同一事务内提交。SQL触发器保护参数、快照及审计不被覆盖。schema1到2迁移保留原事件和任务，不补造历史操作。')

    page('三 数据质控与模型服务')
    h('1 数据入口')
    p('每场洪水必须提交自身state0。数据校验包括必需列、空值、负值、NaN或Inf、时间重复、乱序和非6小时间隔，并按六站泰森权重复算面雨量。ERROR数据留档但禁止起报；面雨量偏差超过阈值记为WARNING，计算使用复算值。畸形CSV的未闭合引号、额外列和超长字段也转成质控错误，避免接口返回500。')
    p('未来预报允许没有Q实测，此时指标为空。部分Q缺测时仅对有效时段计算DC和RMSE，不压缩时间轴计算峰现误差；零方差实测的DC为空。P、EM或站雨量缺测不自动填补。')
    h('2 一期引擎复用')
    p('沿用一期evapotranspire、runoff、split_sources、route及simulate纯函数模块，params只读，动态state显式传入返回，无全局动态状态。每步水量平衡断言保持启用。流域面积2000平方千米、步长6小时，毫米到流量换算严格使用课程指定U=92.6。')
    p('学生数据包v2采用CS线性水库与马斯京根汇流，保留可选单位线模式，不用其他版本模型替换课程口径。二期未重新率定；event4在一期已完成最终检验，二期将其作为固定回归场，不再称为新的盲测。观测Q只用于业务评估，不发送给模型计算接口。')
    h('3 持久任务执行')
    p('POST起报返回202及任务ID，状态依次为QUEUED、RUNNING、SUCCEEDED或FAILED。worker使用原子领取避免重复计算，任务保存输入、参数、初态和算法SHA。模型请求超时30秒；RUNNING超过120秒租约转FAILED并产生通知，用户可显式回放重算，系统不静默覆盖原记录。')

    page('四 产品治理与自动运行')
    h('1 产品复核签发')
    p('预报员从成功任务创建产品草稿，值班长依次复核、签发和发布，状态为DRAFT、REVIEWED、SIGNED、PUBLISHED。错误角色返回403，越级流转返回409，未发布产品的匿名查询返回404。只有签发后的产品可导出正式JSON；发布同时写入通知出站队列，所有步骤保存操作者与内容摘要。')
    h('2 参数方案和回放')
    p('管理员只能新增参数集版本，不能修改已有版本。方案绑定参数和模型版本，支持激活、稳定灰度和回滚；事件指纹决定灰度分桶，显式选择方案则直接采用所选版本。活动、回滚及启用计划引用的方案受归档保护。注册模型元信息不会自动部署镜像，算法SHA未部署时拒绝激活或历史回放。')
    p('回放从原快照新建任务，保留原结果并比较完整Q序列。模型或参数版本切换不影响已创建任务。历史复盘可导出误差分析和过程线，审计按实体查询形成操作链。')
    h('3 自动计划与通知')
    p('scheduler每秒轮询计划，质控默认60秒巡检。计划在数据库中持久化，重启后继续执行，错过多个周期合并为一次，避免集中补报。异常告警按指纹去重，可人工确认。通知投递失败按5秒配置退避，最多3次后进入死信，管理员可重试；本地收件箱通过唯一出站ID避免重复投递。')
    h('4 角色配置与局限')
    p('预报员、值班长、管理员和模型服务使用不同环境密钥，权限在接口执行前检查。该方案适合个人本机教学，不能代替生产多用户身份认证。系统只绑定本机端口；数据库完全不可写时，失败只能先留在容器日志，恢复后再继续处理。')

    page('五 测试结果与模型精度')
    p('最终容器测试共33项通过，0失败、0跳过，运行12.04秒，包含四场全过程黄金回归、水量平衡、异常数据、租约、迁移、角色、快照、签发、灰度回滚、调度与通知故障。存在15条第三方弃用警告，未隐藏。真实HTTP验收逐时段Q与一期基线最大差为0。')
    table(['场次','DC','RMSE m³/s','洪峰误差 %','峰时误差 h'],[
        [r['event'],f"{r['metrics']['DC']:.6f}",f"{r['metrics']['RMSE']:.3f}",
         f"{r['metrics']['peak_relative_error_pct']:.3f}",f"{r['metrics']['peak_time_error_h']:.0f}"] for r in runs])
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.keep_with_next = True
    para.add_run().add_picture(str(OUT/'event4.png'),width=Cm(16))
    para = doc.add_paragraph('图1 event4实测与模拟过程线 蓝色为实测 橙色为模拟','Caption')
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p('event4的DC为0.994047，高于0.85目标，RMSE约8.783立方米每秒，洪峰相对误差约−0.597%，峰现误差0小时。6小时采样下峰时一致只说明离散峰值落在同一时段，不代表峰时精确到小时。结果图和指标来自冻结模型，不以二期业务功能重新拟合检验场。')

    page('六 部署验收与运维设计')
    h('1 可复现部署')
    p('Dockerfile固定Python3.12基础镜像摘要，requirements.lock锁定依赖。仓库根目录执行docker compose up -d --build --wait api worker，依赖关系自动拉起四项服务并等待健康。SQLite保存于命名卷，常规停止和升级不删除卷。最终版还使用独立Compose项目及新卷完成首次部署和完整HTTP流程验证。')
    table(['检查','实际结果','范围说明'],[
        ['四场起报','约0.54至1.07秒完成','每场40时段，本机低负载'],
        ['12任务批量',f"{burst['elapsed_seconds']:.3f}秒，Q差0",'有限批次，不代表通用吞吐SLA'],
        ['真实服务重启','计划触发1次，快照与Q不变','实际重启worker和scheduler'],
        ['自动质控通知','43.435秒，未调用手动扫描','本地值班收件箱，不含外部群'],
        ['远程CI',ci['conclusion'],'GitHub运行号 '+str(ci['id'])]])
    h('2 备份和恢复')
    p('升级前使用SQLite backup API创建一致备份，并通过PRAGMA integrity_check检查，不能只复制运行中主库而遗漏WAL。运维手册提供将备份恢复至独立项目卷的方法，先查询历史任务与审计，再决定正式切换。恢复旧库时需匹配原schema和应用版本，不直接用旧代码打开新schema。')
    h('3 持续集成')
    p('GitHub Actions执行锁定依赖安装、pytest、Compose部署、真实HTTP流程、有限批量及进程重启验收，上传JUnit与业务JSON证据，结束后停止测试服务。完整提交历史和CI配置纳入仓库，最终提交包附Git bundle及SHA256清单。CI运行链接和对应提交摘要在最终测试报告中记录。')

    page('七 个人总结与交付说明')
    h('1 技术选择与代价')
    p('本项目选择Python与FastAPI，便于复用一期计算引擎并从实际路由生成OpenAPI；SQLite适合单机课程数据量，部署简单，但不支持本方案的多机并发写入；单worker配持久任务表降低重复执行风险，同时限制吞吐。计划执行由独立进程承担，避免API重启或请求处理阻塞自动业务。')
    p('为保留可复现性，参数采用不可变版本、任务采用完整快照。代价是数据存储量增加，旧算法还需要配套镜像才能回放。通知使用事务出站队列与本地收件箱，能验证重试和幂等，但没有证明真实外部通道的送达能力。')
    h('2 主要工程认识')
    p('一期重点是公式与水量守恒，二期进一步把正确计算放入可追踪的业务流程。数据有误仍需要留档，计算失败需要有状态和原因，结果签发需要权限与顺序，方案切换需要保留旧任务的原版本。通过快照、事务和故障测试，系统从能运行一次的脚本转为可以检查历史行为的本地服务。')
    p('本次验收没有把本地测试当成远程CI，也没有把一次低负载测量当成一般性能保证。后续若扩展到多人使用，应补充用户身份体系、数据库迁移策略、外部通知适配、模型多版本部署及更大数据和长时间故障压力验证。')
    h('3 交付清单')
    p('交付包括完整Git仓库、Dockerfile与Compose、锁定依赖、自动化测试和CI、黄金与异常数据、SRS、数据库设计、业务与模型OpenAPI、README、运维手册、演示步骤、最终验收清单、测试证据以及本个人总结报告的Word和PDF版本。工程和文档分别打包，运行数据库及密钥不随包提交。')
    p('个人信息为河海大学计算机与软件学院软件工程专业24级1班陈一，学号2406050103。本报告按个人实际交付范围组织，不列虚构小组成员。')
    target = ROOT/'reports'
    target.mkdir(exist_ok=True)
    filename = target/'陈一_2406050103_洪水预报系统二期总结报告.docx'
    doc.save(filename)
    print(filename)


if __name__=='__main__':
    main()
