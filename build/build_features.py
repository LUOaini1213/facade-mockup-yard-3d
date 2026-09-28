"""First version of model/site_features.json (instanced palms / shrubs / people / cars and label anchors in the glTF
site frame). Superseded by build_features2.py.
"""
import numpy as np, json, math
from site_frame import r3_to_gltf, page_to_r3, r3_dir_to_gltf, s as S_PT
rng = np.random.default_rng(7)
ROAD_A = np.array([307.08, 693.0]); ROAD_B = np.array([811.8, 738.36]); u = (ROAD_B - ROAD_A) / np.linalg.norm(ROAD_B - ROAD_A)
nrm = np.array([-u[1], u[0]])
def g(px, py, z=0.0): return r3_to_gltf(page_to_r3(px, py)[None, :], z)[0].round(3).tolist()

palms = []
for t in np.arange(-10, 1150, 9.0 / S_PT):
    p = ROAD_A + u * t + nrm * (3.5 / S_PT)
    palms.append(dict(p=g(*p), h=round(float(rng.uniform(9.5, 13.5)), 2), lean=round(float(rng.uniform(-0.06, 0.06)), 3), rot=round(float(rng.uniform(0, 6.283)), 3)))
for t in np.arange(0, 1150, 14.0 / S_PT):
    p = ROAD_A + u * t + nrm * (30.0 / S_PT)
    palms.append(dict(p=g(*p), h=round(float(rng.uniform(8, 11)), 2), lean=round(float(rng.uniform(-0.05, 0.05)), 3), rot=round(float(rng.uniform(0, 6.283)), 3)))
shrubs = [dict(p=g(*(ROAD_A + u * t + nrm * (1.6 / S_PT))), r=round(float(rng.uniform(0.6, 1.1)), 2)) for t in np.arange(0, 1150, 2.5 / S_PT)]

people = []
spots = [(580, 585), (590, 600), (605, 480), (652, 500), (592, 652), (560, 690), (520, 662), (525, 592), (656, 642), (605, 540)]
vest = ['#f2c200', '#ff7a00', '#2d6cdf', '#f2c200', '#ffffff', '#f2c200', '#e84b3c', '#ff7a00', '#2d6cdf', '#f2c200']
for (px, py), c in zip(spots, vest):
    people.append(dict(p=g(px, py), rot=round(float(rng.uniform(0, 6.283)), 2), vest=c, h=round(float(rng.uniform(1.62, 1.82)), 2)))
for k, py in enumerate((470.0, 486.0, 505.0)):
    people.append(dict(p=g(464.0, py, 3.0), rot=1.57, vest=['#f2c200', '#ffffff', '#ff7a00'][k], h=1.72))

cars = []
for k, py in enumerate(np.arange(440.0, 690.0, 12.5)):
    if rng.random() < 0.35: continue
    cars.append(dict(p=g(372.0, py), rot=0.0, color=['#d9dcdf', '#1d1f22', '#8a9096', '#b2261d', '#27496d', '#f0f0ec'][k % 6]))
for k, py in enumerate(np.arange(446.0, 690.0, 12.5)):
    if rng.random() < 0.55: continue
    cars.append(dict(p=g(440.0, py), rot=math.pi, color=['#f0f0ec', '#5b5f63', '#1d1f22', '#c8ccd0'][k % 4]))
axis_x = r3_dir_to_gltf(np.array([1.0, 0]))[0].round(4).tolist(); axis_y = r3_dir_to_gltf(np.array([0, 1.0]))[0].round(4).tolist()

labels = {
    'VMU01': dict(zh='VMU-01 塔楼单元式幕墙 + 装饰构件 + 雨棚', en='VMU-01 Tower unitised CW + cladding + canopy'),
    'VMU01_EXT': dict(zh='VMU-01 雨棚延伸（新增）', en='VMU-01 canopy extension (new)', p=None),
    'VMU02': dict(zh='VMU-02 围合样板（推拉门）', en='VMU-02 Enclosure sample'),
    'VMU03': dict(zh='VMU-03 弧形裙楼立面（水平装饰翼）', en='VMU-03 Curved podium facade'),
    'VMU04': dict(zh='VMU-04 竖向转角样板', en='VMU-04 Vertical corner'),
    'VMU05': dict(zh='VMU-05 低位弧形栏杆样板', en='VMU-05 Low curved balustrade'),
    'TRELLIS': dict(zh='Trellis 铝格栅屋面', en='Aluminium roof trellis'),
}
ctx_labels = [dict(zh='2层厂房', p=g(486.5, 140.0, 26.0)), dict(zh='1层厂房', p=g(486.5, 320.0, 15.5)),
              dict(zh='集装箱 + 临时观景钢平台', p=g(464.0, 560.0, 5.0)), dict(zh='主路', p=g(560.0, 745.0, 1.5)),
              dict(zh='消防车道', p=g(669.0, 300.0, 0.5)), dict(zh='预制件堆场', p=g(760.0, 420.0, 1.0)), dict(zh='临时停车区', p=g(406.0, 520.0, 0.5)),
              dict(zh='材料堆放区', p=g(330.0, 560.0, 2.0))]
json.dump(dict(palms=palms, shrubs=shrubs, people=people, cars=cars, axis_x=axis_x, axis_y=axis_y, labels=labels, ctx_labels=ctx_labels,
               lot_boundary=[g(307.08, -330.0), g(307.08, 693.0), g(*(ROAD_A + u * 1150))]), open('../model/site_features.json', 'w'), indent=0)
print(len(palms), len(shrubs), len(people), len(cars))
