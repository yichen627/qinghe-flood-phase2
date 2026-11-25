"""只对已成功任务生成科学过程图，不重新计算或改变参数。"""
from io import BytesIO
from datetime import datetime
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
import numpy as np


def forecast_png(snapshot,result):
    """蓝色实测、橙色模拟，标注首次最大值；无观测仍能画图。"""
    rows = snapshot['event_rows']
    times = [datetime.fromisoformat(row['time']) for row in rows]
    fig = Figure(figsize=(10,4.8),layout='constrained')
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    observed = [np.nan if r['Q_obs'] is None else r['Q_obs'] for r in rows]
    if any(r['Q_obs'] is not None for r in rows):
        ax.plot(times,observed,color='#2166ac',label='Observed')
    q = result['simulation']['Q']
    ax.plot(times,q,color='#ef8a23',label='Simulated')
    peak = int(np.argmax(q))
    ax.annotate(f'Simulated peak {q[peak]:.1f}\n{times[peak]:%m-%d %H:%M}',
                (times[peak],q[peak]),xytext=(12,18),textcoords='offset points',fontsize=8)
    ax.set_title('Qinghe forecast | '+snapshot['source'])
    ax.set_ylabel('Discharge (m³/s)')
    ax.set_xlabel('Time (6 h interval, UTC+08:00 for course data)')
    ax.grid(alpha=.2)
    ax.legend()
    ax.margins(y=.25)
    fig.autofmt_xdate()
    stream = BytesIO()
    fig.savefig(stream,format='png',dpi=160)
    return stream.getvalue()
