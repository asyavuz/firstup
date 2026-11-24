"""Makes docs/images/paper.png: a receipt, the poster and a page of trains lying on a table. Not a
photograph: a small path tracer in Chrome lights exactly what the printer is sent, with the
made-up data of make_pictures.py. Run on a Mac, needs Chrome:

    .venv/bin/python tools/make_renders.py
"""

import base64
import http.server
import io
import json
import subprocess
import tempfile
import threading
import time
from datetime import datetime

import make_pictures as pictures  # first: it sets the open font and nobody's own settings
from PIL import Image

from reporter import config, poster, trains

WIDTH, HEIGHT, PASSES = 1600, 1060, 1200
PAPER = 464  # dots across 58 mm, of which 384 are printed

TRACE = """#version 300 es
precision highp float; precision highp int;
uniform sampler2D RECEIPT, POSTER, TRAINS; uniform vec2 RES; uniform int PASS; out vec4 OUT;
const float PI = 3.14159265;
uvec4 st;
float rnd() { st = st*1664525u+1013904223u; st.x+=st.y*st.w; st.y+=st.z*st.x; st.z+=st.x*st.y; st.w+=st.y*st.z; st^=st>>16u;
  st.x+=st.y*st.w; st.y+=st.z*st.x; st.z+=st.x*st.y; st.w+=st.y*st.z; return float(st.x)/4294967295.; }
struct Hit { float t; vec3 n, colour; };
vec3 lin(vec3 c) { return pow(c, vec3(2.2)); }

// A strip of paper, bent over a cylinder of radius R, turned by `a` and lying at `o`. Centimetres.
void strip(sampler2D T, vec3 ro, vec3 rd, float R, float a, vec3 o, float far, inout Hit h) {
  vec2 size = vec2(textureSize(T, 0)); float L = size.y/80., first = PI/2.-L/2./R, ca = cos(a), sa = sin(a);
  vec2 C = vec2(.03-R*cos(L/2./R), 0.);
  ro -= o; ro = vec3(ca*ro.x-sa*ro.z, ro.y, sa*ro.x+ca*ro.z); rd = vec3(ca*rd.x-sa*rd.z, rd.y, sa*rd.x+ca*rd.z);
  vec2 q = ro.yz-C, d = rd.yz; float A = dot(d,d), B = dot(q,d), D = B*B-A*(dot(q,q)-R*R); if (D < 0. || A < 1e-9) return; D = sqrt(D);
  for (int i = 0; i < 2; i++) {
    float t = (-B+(i == 0 ? -D : D))/A; if (t < .004 || t > min(far, h.t)) continue;
    vec3 p = ro+rd*t; vec2 v = p.yz-C; float s = (atan(v.x, v.y)-first)*R; if (abs(p.x) > 2.9 || s < 0. || s > L) continue;
    if (L-s < .05+.05*abs(fract(p.x*4.)-.5)*2.) continue;  // the torn edge
    vec3 n = vec3(0., v/R); vec2 uv = vec2((p.x+2.9)*80., (L-s)*80.)/size;
    h = Hit(t, vec3(ca*n.x+sa*n.z, n.y, -sa*n.x+ca*n.z), mix(lin(vec3(.17,.17,.20)), lin(vec3(.955,.945,.92)), texture(T, uv).r)); return;
  }
}
void strips(vec3 ro, vec3 rd, float far, inout Hit h) {
  strip(RECEIPT, ro, rd, 70., .07, vec3(-7.3,0.,.5), far, h);
  strip(POSTER, ro, rd, 24., -.09, vec3(.7,0.,-3.), far, h);
  strip(TRAINS, ro, rd, 16., .14, vec3(8.,0.,4.), far, h);
}
bool trace(vec3 ro, vec3 rd, inout Hit h) {
  h.t = 1e4;
  if (rd.y < 0. && -ro.y/rd.y > .004) {
    float t = -ro.y/rd.y; vec3 p = ro+rd*t;
    float grain = fract(sin(dot(floor(p.xz*vec2(.9,26.)), vec2(12.98,78.2)))*43758.5), wave = .5+.5*sin(p.x*.35+6.*sin(p.z*.12+.4*sin(p.x*.5)));
    h = Hit(t, vec3(0.,1.,0.), lin(vec3(.085,.20,.28))*(.93+.06*wave+.03*grain));
  }
  strips(ro, rd, 1e4, h); return h.t < 1e4;
}
vec3 scatter(vec3 n) { float a = 2.*PI*rnd(), z = 2.*rnd()-1.; return normalize(n+vec3(sqrt(1.-z*z)*vec2(cos(a),sin(a)), z)*.999); }
vec3 light(vec3 ro, vec3 rd) {
  vec3 sum = vec3(0.), left = vec3(1.);
  for (int bounce = 0; bounce < 4; bounce++) {
    Hit h; if (!trace(ro, rd, h)) return sum+left*mix(vec3(.95,.80,.62), vec3(.62,.76,.92), clamp(rd.y*.5+.5, 0., 1.))*.62;
    vec3 n = dot(h.n, rd) > 0. ? -h.n : h.n; ro += rd*h.t+n*.006; left *= h.colour;
    vec3 l = vec3(-19.+8.*rnd(), 21.+4.*rnd(), -15.+8.*rnd())-ro; float d = length(l); l /= d;
    Hit shadow; shadow.t = d; strips(ro, l, d, shadow);
    if (dot(n, l) > 0. && shadow.t >= d) sum += left*vec3(1.,.93,.80)*dot(n, l)*446./(d*d);
    rd = scatter(n);
  }
  return sum;
}
void main() {
  st = uvec4(uint(gl_FragCoord.x), uint(gl_FragCoord.y), uint(PASS), uint(PASS)*7u+11u); rnd(); rnd();
  vec2 q = (gl_FragCoord.xy+vec2(rnd(),rnd())-.5-.5*RES)/RES.y;
  vec3 eye = vec3(.4,38.,6.5), w = normalize(vec3(.4,0.,.35)-eye), u = normalize(cross(w, vec3(0.,0.,-1.))), v = cross(u, w);
  vec3 c = light(eye, normalize(q.x*u+q.y*v+1.8*w)); OUT = vec4(any(isnan(c)) ? vec3(0.) : min(c, vec3(6.)), 1.);
}"""

DEVELOP = """#version 300 es
precision highp float; uniform sampler2D SUM; uniform vec2 RES; out vec4 OUT;
void main() {
  vec4 c = texelFetch(SUM, ivec2(gl_FragCoord.xy), 0); vec2 q = gl_FragCoord.xy/RES-.5; vec3 x = c.rgb/c.a*(1.-.28*dot(q, q))*1.06;
  OUT = vec4(pow(clamp((x*(2.35*x+.06))/(x*(2.2*x+.62)+.14), 0., 1.), vec3(1./2.2)), 1.);
}"""

PAGE = """<!doctype html><meta charset=utf-8><canvas id=c width=%(width)d height=%(height)d></canvas><script>
const answer = (path, body) => fetch(path, {method: "POST", body});
(async () => {
  const W = c.width, H = c.height, gl = c.getContext("webgl2", {preserveDrawingBuffer: true});
  gl.getExtension("EXT_color_buffer_float"); gl.getExtension("EXT_float_blend"); gl.bindVertexArray(gl.createVertexArray());
  const program = source => {
    const p = gl.createProgram(), corner = "#version 300 es\\nvoid main(){vec2 p=vec2((gl_VertexID<<1)&2,gl_VertexID&2);gl_Position=vec4(p*2.-1.,0,1);}";
    for (const [kind, text] of [[gl.VERTEX_SHADER, corner], [gl.FRAGMENT_SHADER, source]]) {
      const s = gl.createShader(kind); gl.shaderSource(s, text); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw gl.getShaderInfoLog(s);
      gl.attachShader(p, s);
    }
    gl.linkProgram(p); gl.useProgram(p); gl.uniform2f(gl.getUniformLocation(p, "RES"), W, H); return p;
  };
  const trace = program(%(trace)s);
  for (const [i, [name, data]] of %(papers)s.entries()) {
    const image = new Image(); image.src = data; await image.decode();
    gl.activeTexture(gl.TEXTURE0 + i); gl.bindTexture(gl.TEXTURE_2D, gl.createTexture()); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.uniform1i(gl.getUniformLocation(trace, name), i);
  }
  gl.activeTexture(gl.TEXTURE8); const sum = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, sum); gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA32F, W, H);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
  gl.bindFramebuffer(gl.FRAMEBUFFER, gl.createFramebuffer()); gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, sum, 0);
  gl.viewport(0, 0, W, H); gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE); gl.enable(gl.SCISSOR_TEST);
  for (let k = 0; k < %(passes)d; k++) {  // in small pieces, or the graphics chip gives up
    gl.uniform1i(gl.getUniformLocation(trace, "PASS"), k + 1);
    for (let n = 0; n < 16; n++) { gl.scissor(n %% 4 * W / 4, (n >> 2) * H / 4, W / 4, H / 4); gl.drawArrays(gl.TRIANGLES, 0, 3); }
    gl.finish(); if (gl.isContextLost()) throw "the graphics chip gave up"; if (k %% 2) await new Promise(r => setTimeout(r, 4));
  }
  gl.disable(gl.SCISSOR_TEST); gl.disable(gl.BLEND); gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  const develop = program(%(develop)s); gl.uniform1i(gl.getUniformLocation(develop, "SUM"), 8); gl.drawArrays(gl.TRIANGLES, 0, 3); gl.finish();
  c.toBlob(b => answer("/picture", b));
})().catch(e => answer("/problem", String(e)));</script>"""


def paper(printed: Image.Image, margin: int = 56) -> str:
    """With the white round it, as a data address."""
    sheet, out = Image.new("L", (PAPER, printed.height + 2 * margin), 255), io.BytesIO()
    sheet.paste(printed.convert("L"), ((PAPER - printed.width) // 2, margin))
    sheet.save(out, "PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def departures(now: datetime) -> Image.Image:
    rows = (("14", "On time"), ("12", "08:13"), ("14", "On time"), ("12", "Cancelled"), ("14", "On time"))
    found = [trains.Train(now.replace(minute=4 + 6 * i), "London Victoria", platform, expected) for i, (platform, expected) in enumerate(rows)]
    return trains.page(config.TrainSettings(station="CLJ", towards="VIC"), trains.Board("Clapham Junction", found), now)


def render(html: bytes, patience: int = 240) -> Image.Image:
    """Chrome gets the page from here and sends the picture back here."""
    answers = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)

        def do_POST(self):
            answers[self.path] = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(204)
            self.end_headers()

        def log_message(self, *args):
            pass

    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        chrome = subprocess.Popen([pictures.CHROME, "--headless=new", "--use-angle=metal", "--ignore-gpu-blocklist", "--remote-debugging-port=0", "--no-first-run",
                                   f"--user-data-dir={folder}", f"http://127.0.0.1:{server.server_address[1]}/"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        until = time.monotonic() + patience
        while not answers and time.monotonic() < until:
            time.sleep(.2)
        chrome.terminate()
        chrome.wait(20)
        server.shutdown()
    if "/picture" not in answers:
        raise RuntimeError(answers.get("/problem", b"Chrome made no picture").decode())
    return Image.open(io.BytesIO(answers["/picture"])).convert("RGB")


if __name__ == "__main__":
    morning = datetime(2026, 11, 25, 8, 0, tzinfo=config.load().tz)
    papers = [("RECEIPT", paper(pictures.sample_receipt(morning))), ("POSTER", paper(poster.page(morning))), ("TRAINS", paper(departures(morning)))]
    page = PAGE % {"width": WIDTH, "height": HEIGHT, "passes": PASSES, "trace": json.dumps(TRACE), "develop": json.dumps(DEVELOP), "papers": json.dumps(papers)}
    render(page.encode()).save(pictures.ROOT / "docs/images/paper.png", optimize=True)
