from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import pathlib,gzip,urllib.parse,mimetypes
ROOT=pathlib.Path('/tmp/raiz-comparacao-openlayers/dist');cache={}
for p in ROOT.rglob('*'):
 if p.is_file():
  data=p.read_bytes();ty=mimetypes.guess_type(str(p))[0] or 'application/octet-stream';compressed=p.suffix in ['.js','.css','.json','.geojson','.html','.mjs'];cache['/'+str(p.relative_to(ROOT))]=(gzip.compress(data,mtime=0) if compressed else data,ty,compressed)
class H(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  url=urllib.parse.urlsplit(self.path).path
  if url=='/':url='/index.html'
  if url not in cache:self.send_error(404);return
  data,ty,compressed=cache[url];self.send_response(200);self.send_header('Content-Type',ty);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
  if compressed:self.send_header('Content-Encoding','gzip')
  self.end_headers()
  try:self.wfile.write(data)
  except (BrokenPipeError,ConnectionResetError):pass
ThreadingHTTPServer(('127.0.0.1',8765),H).serve_forever()
