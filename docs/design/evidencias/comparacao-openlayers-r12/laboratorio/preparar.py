import json,gzip,hashlib,math,pathlib,urllib.request
from shapely.geometry import shape,mapping,box,Point
root=pathlib.Path('/tmp/raiz-comparacao-openlayers-corrigida');pub=root/'public';(pub/'dados').mkdir(parents=True,exist_ok=True)
orig=pathlib.Path('/tmp/raiz-fontes-final-real-site/geo/imoveis_1505536.geojson.gz');fc=json.load(gzip.open(orig));fs=fc['features']
fs.sort(key=lambda f:-shape(f['geometry']).area)
for i,f in enumerate(fs):f['id']=i;f['properties']['ordem_desenho']=-shape(f['geometry']).area
(pub/'dados/imoveis.geojson').write_text(json.dumps(fc,separators=(',',':')))
R=6378137;W=2*math.pi*R
merc=lambda p:[R*math.radians(p[0]),R*math.log(math.tan(math.pi/4+math.radians(p[1])/2))]
inv=lambda p:[math.degrees(p[0]/R),math.degrees(2*math.atan(math.exp(p[1]/R))-math.pi/2)]
cases={}; tiles=set()
for name,code in [('com','PA-1505536-D2B09F9982D146B689FB0604539AC352'),('sem','PA-1505536-7732C1F0A1784452A42A2C3FF72273CA')]:
 f=next(f for f in fs if f['properties']['cod_imovel']==code);g=shape(f['geometry']);b=g.bounds;lo=merc(b[:2]);hi=merc(b[2:]);center=[(lo[0]+hi[0])/2,(lo[1]+hi[1])/2]
 views={str(w):{'center':center,'resolution':max((hi[0]-lo[0])/(w-64),(hi[1]-lo[1])/(640-64),W/512/2**16)} for w in [360,960]}
 ints=[a for a in fs if a['id']!=f['id'] and shape(a['geometry']).is_valid and g.intersection(shape(a['geometry'])).area>1e-12]
 points=[]
 # O ponto de interseção é testado primeiro; nenhum dado privado é inferido.
 if ints:
  p=g.intersection(shape(ints[-1]['geometry'])).representative_point();points.append(('cruzamento',p))
 free=g
 for a in ints:free=free.difference(shape(a['geometry']))
 points.append(('interior',free.representative_point() if not free.is_empty else g.representative_point()))
 points.append(('exterior',Point(b[0]-.003,b[1]-.003)))
 tests=[]
 for label,p in points:
  hits=[a for a in fs if shape(a['geometry']).is_valid and shape(a['geometry']).covers(p)]
  hits.sort(key=lambda a:shape(a['geometry']).area)
  tests.append({'label':label,'lnglat':[p.x,p.y],'expected':hits[0]['id'] if hits else None,'all_ids':[a['id'] for a in hits]})
 masks={str(f['id']):{'type':'Feature','properties':{},'geometry':mapping(box(-180,-85,180,85).difference(g))}}
 for test in tests:
  if test['expected'] is not None:
   a=fs[test['expected']];masks[str(a['id'])]={'type':'Feature','properties':{},'geometry':mapping(box(-180,-85,180,85).difference(shape(a['geometry'])))}
 r=views['360']['resolution']*2**.35;extent=[center[0]-(360/2+180)*r,center[1]-(640/2+100)*r,center[0]+(360/2+180)*r,center[1]+(640/2+100)*r]
 # margem de 1 tile cobre arredondamento dos motores e confirmação desktop.
 for z in [14]:
  n=2**z;a=[math.floor((extent[0]+W/2)/W*n)-1,math.floor((W/2-extent[3])/W*n)-1];b2=[math.floor((extent[2]+W/2)/W*n)+1,math.floor((W/2-extent[1])/W*n)+1]
  for x in range(a[0],b2[0]+1):
   for y in range(a[1],b2[1]+1):tiles.add((z,x,y))
 cases[name]={'target':f['id'],'code':code,'views':views,'tests':tests,'mask':masks,'bounds':b,'control_points':[b[:2],b[2:],[b[0],b[3]],[b[2],b[1]],list(g.representative_point().coords)[0]],'overlaps':len(ints)}
(pub/'dados/casos.json').write_text(json.dumps(cases,separators=(',',':')))
manifest={'source':str(orig),'source_sha256':hashlib.sha256(orig.read_bytes()).hexdigest(),'features':len(fs),'bytes':(pub/'dados/imoveis.geojson').stat().st_size,'cases':cases,'tiles':[]}
for z,x,y in sorted(tiles):
 rel=f'tiles/{z}/{x}/{y}.jpg';p=pub/rel;p.parent.mkdir(parents=True,exist_ok=True);url=f'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/GoogleMapsCompatible/{z}/{y}/{x}.jpg'
 if not p.exists():
  with urllib.request.urlopen(url,timeout=30) as q:data=q.read();assert data[:2]==b'\xff\xd8';p.write_bytes(data)
 manifest['tiles'].append({'file':rel,'source':url,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size,'license':'CC BY 4.0','vintage':'2016/2017'})
manifest['prepared_sha256']=hashlib.sha256((pub/'dados/imoveis.geojson').read_bytes()).hexdigest()
(root/'dados-manifesto.json').write_text(json.dumps(manifest,indent=2))
print(json.dumps({'features':len(fs),'bytes':manifest['bytes'],'tiles':len(tiles),'cases':{k:{'target':v['target'],'overlaps':v['overlaps'],'tests':v['tests'],'resolution':v['views']['360']['resolution']} for k,v in cases.items()}},indent=2))
