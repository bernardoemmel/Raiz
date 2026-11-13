import json,math,numpy as np
from PIL import Image
W=40075016.68557849;c=json.load(open('public/dados/casos.json'))['com'];f=json.load(open('public/dados/imoveis.geojson'))['features'][c['target']];report={}
for width in [360,960]:
 v=c['views'][str(width)];pts=[]
 for lon,lat in f['geometry']['coordinates'][0]:
  pts.append(np.array([(lon/360*W-v['center'][0])/v['resolution']+width/2,320-(math.log(math.tan(math.pi/4+lat*math.pi/360))*W/(2*math.pi)-v['center'][1])/v['resolution']+60]))
 a,b=pts[5],pts[6];d=b-a;length=np.linalg.norm(d);unit=d/length;normal=np.array([-unit[1],unit[0]]);expected=6*2**(math.log2(W/512/v['resolution'])%1);r={'expected_period_px':expected,'engines':{}}
 for engine in ['ml','ol']:
  image=np.asarray(Image.open(f'functional-paridade/com-{width}-00-{engine}-normal.png'))[:,:,:3].mean(axis=2)
  def pixel(p):
   x,y=p;ix,iy=int(x),int(y);fx,fy=x-ix,y-iy
   return image[iy,ix]*(1-fx)*(1-fy)+image[iy,ix+1]*fx*(1-fy)+image[iy+1,ix]*(1-fx)*fy+image[iy+1,ix+1]*fx*fy
  positions=np.arange(20,length-20,.25);profile=[]
  for distance in positions:
   center=a+unit*distance;bg=(pixel(center+normal*5)+pixel(center-normal*5))/2;foreground=min(pixel(center+normal*t) for t in [-.5,0,.5]);profile.append(bg-foreground)
  profile=np.array(profile);profile-=profile.mean();candidates=np.arange(expected*.8,expected*1.2,.25)
  corr=[]
  for period in candidates:
   lag=round(period/.25);corr.append(float(np.corrcoef(profile[:-lag],profile[lag:])[0,1]))
  best=int(np.argmax(corr));r['engines'][engine]={'measured_period_px':round(float(candidates[best]),2),'autocorrelation':round(corr[best],3)}
 report[str(width)]=r
open('paridade-tracejado.json','w').write(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
