"""Writes georef.json: scale of the layout plan (m per PDF point), bearing of the plan axes and the yard origin in plan
metres. The plan bearing is the surveyed bearing of the south lot line, read from the private survey extract when it is
present (SOURCES_DIR/site_survey.json, lot_south_line.bearing_deg); without it the rounded 290.34 deg is used (the frame
then turns by less than 0.003 deg, under 0.01 m at 200 m). The geographic origin of the site is not part of the public build.
"""
import os, numpy as np, math, json
SOURCES_DIR = os.environ.get('MOCKUP_SOURCES', 'sources')
try:
    BRG = float(json.load(open(os.path.join(SOURCES_DIR, 'site_survey.json'), encoding='utf-8'))['lot_south_line']['bearing_deg'])
except (OSError, KeyError, ValueError):
    BRG = 290.34
s=15000/71.645/1000.0
b=math.radians(BRG-270)
O=np.array([120.0,-118.0])
meta=dict(R3_scale_m_per_pt=s,plan_y_bearing=BRG,plan_x_bearing=math.degrees(b),origin_R3m=O.tolist())
json.dump(meta,open('georef.json','w'),indent=1); print(json.dumps(meta,indent=1))
