"""六站CSV解析与质控，原始问题只标记、不插补。"""
import csv
import io
import math
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo


def inspect_csv(text,rules):
    """返回可严格JSON编码的标准记录与全部质控问题。"""
    issues,rows = [],[]

    def issue(severity,code,line,field,message):
        """追加结构化问题，保留原CSV行号。"""
        issues.append(dict(severity=severity,code=code,row=line,field=field,message=message))

    def number(row,key,line,optional=False):
        """转换有限非负数；观测Q问题仅告警，不影响无观测预报。"""
        severity = 'WARNING' if optional else 'ERROR'
        raw = row.get(key)
        try:
            if raw is None or not raw.strip() or raw.strip() == '-999':
                raise ValueError('missing')
            value = float(raw)
            if not math.isfinite(value) or value < 0:
                raise ValueError('nonfinite_or_negative')
            return value
        except (ValueError,TypeError):
            issue(severity,'INVALID_NUMBER',line,key,'缺测、负值或非有限数')
            return None

    if len(text.encode('utf-8')) > rules['max_csv_bytes']:
        raise ValueError('CSV超过配置的大小上限')
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    station_columns = {f'P_{key}(mm)':value for key,value in rules['station_weights'].items()}
    mandatory = ['时间',*station_columns,'面雨量P(mm)','蒸发皿EM(mm)']
    for key in mandatory:
        if key not in (reader.fieldnames or []):
            issue('ERROR','MISSING_COLUMN',1,key,'缺少必要列')
    if any(i['code']=='MISSING_COLUMN' for i in issues):
        return rows,issues
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        issue('ERROR','DUPLICATE_COLUMN',1,'header','重复列名')
    previous = None
    for line,row in enumerate(reader,2):
        if len(rows) >= rules['max_event_rows']:
            issue('ERROR','TOO_MANY_ROWS',line,'CSV','行数超过配置限制')
            break
        try:
            moment = datetime.fromisoformat(row['时间'])
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=ZoneInfo(rules['timezone']))
            if previous is not None and moment-previous != timedelta(hours=rules['dt_hours']):
                issue('ERROR','TIME_INTERVAL',line,'时间','重复、乱序或非6h间隔')
            previous = moment
            timestamp = moment.isoformat()
        except (ValueError,TypeError):
            issue('ERROR','INVALID_TIME',line,'时间','时刻缺测或格式非法')
            timestamp = None
        stations = {key:number(row,key,line) for key in station_columns}
        supplied = number(row,'面雨量P(mm)',line)
        em = number(row,'蒸发皿EM(mm)',line)
        rain = (sum(stations[k]*w for k,w in station_columns.items())
                if all(v is not None for v in stations.values()) else None)
        if rain is not None and supplied is not None and abs(rain-supplied)>rules['rainfall_warning_tolerance_mm']:
            issue('WARNING','AREA_RAINFALL_DIFFERENCE',line,'面雨量P(mm)','使用泰森复算值，保留原值')
        observed = number(row,'实测流量Q(m3/s)',line,optional=True) if '实测流量Q(m3/s)' in row else None
        rows.append(dict(time=timestamp,P=rain,EM=em,Q_obs=observed,P_supplied=supplied))
    if not rows:
        issue('ERROR','EMPTY_EVENT',2,'CSV','事件无记录')
    return rows,issues
