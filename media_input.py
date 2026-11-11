"""Screenshots and voice for the owner's messages to the agent.

* A photo (screenshot of the problem) can go with a new request, an answer, or "Still broken". The browser shrinks it first
  (at most 1600 px, JPEG, about 500 KB), which also drops the phone's location data; the server accepts only JPEG / PNG / WebP,
  checks the file really is one, removes any EXIF block that is left, and keeps at most a few per case.
* Voice: a microphone button types what you say into the box with the browser's own speech recognition (free, nothing is sent to
  us until you press Send, and you can correct the text first).

The engineer gets the photos as images next to the request. A screenshot can contain text: it is the owner's evidence, never an
instruction to follow.
"""
from __future__ import annotations

import base64
import html as _html
import re

MAX_IMAGE_BYTES = 700_000
DATA_URL = re.compile(r"^data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=\s]+)$")
MAGIC = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG\r\n\x1a\n", "image/webp": b"RIFF"}


def strip_jpeg_metadata(data: bytes) -> bytes:
    """Remove APP1 (EXIF / XMP: camera, time, GPS location) and comment segments from a JPEG; keep the picture as it is."""
    if not data.startswith(b"\xff\xd8"):
        return data
    out, i = bytearray(b"\xff\xd8"), 2
    while i + 4 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker in (0xD9, 0xDA):                      # end of image / start of the picture data: copy the rest unchanged
            out += data[i:]
            return bytes(out)
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if length < 2 or i + 2 + length > len(data):
            return data                                  # not a JPEG we understand: leave it as it was
        if marker not in (0xE1, 0xFE):                   # APP1 (EXIF / XMP) and COM are dropped
            out += data[i:i + 2 + length]
        i += 2 + length
    out += data[i:]
    return bytes(out)


def parse_data_url(value: str) -> tuple[str, bytes] | None:
    """(mime, bytes) of a safe image, or None. Anything that is not really a small JPEG / PNG / WebP is refused."""
    value = str(value or "").strip()
    if not value:
        return None
    m = DATA_URL.match(value)
    if not m:
        return None
    mime = m.group(1)
    try:
        data = base64.b64decode(re.sub(r"\s", "", m.group(2)), validate=True)
    except (ValueError, base64.binascii.Error):
        return None
    if not data or len(data) > MAX_IMAGE_BYTES or not data.startswith(MAGIC[mime]):
        return None
    if mime == "image/webp" and data[8:12] != b"WEBP":
        return None
    if mime == "image/jpeg":
        data = strip_jpeg_metadata(data)
    return mime, data


def data_url(mime: str, data: bytes) -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def inputs_html(field: str = "text", *, photo: bool = True, voice: bool = True) -> str:
    """The photo and microphone buttons that go under a text box of a form marked data-media."""
    parts = []
    if photo:
        parts.append("<label class='button media-btn'><input type='file' accept='image/*' data-photo hidden>"
                     "<span aria-hidden='true'>📷</span> Add a screenshot</label>"
                     "<input type='hidden' name='image_data' data-photo-data>")
    if voice:
        parts.append(f"<button type='button' class='button media-btn' data-voice='{_html.escape(field)}' hidden>"
                     "<span aria-hidden='true'>🎙</span> <span data-voice-label>Speak</span></button>")
    parts.append("<div class='media-preview' data-photo-preview hidden><img alt='Your screenshot'>"
                 "<button type='button' class='button media-remove' data-photo-remove>Remove</button></div>"
                 "<small class='muted media-note' data-media-note></small>")
    return "<div class='media-row'>" + "".join(parts) + "</div>"


MEDIA_CSS = """
.media-row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:10px 0 14px}
.media-btn{min-height:40px;padding:8px 14px;font-size:14px;cursor:pointer}
.media-btn.listening{border-color:#ff5a4a;box-shadow:0 0 0 3px #e11d2a33;animation:media-pulse 1.2s ease-in-out infinite}
@keyframes media-pulse{50%{box-shadow:0 0 0 6px #e11d2a1a}}
.media-preview{display:flex;align-items:center;gap:10px;flex-basis:100%}
.media-preview img{max-width:180px;max-height:120px;border-radius:10px;border:1px solid #ffffff22;object-fit:cover}
.media-remove{min-height:34px;padding:6px 12px;font-size:13px}
.media-note{flex-basis:100%}
.case-shots{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}
.case-shots a img{width:160px;height:110px;object-fit:cover;border-radius:10px;border:1px solid #ffffff22}
"""

MEDIA_JS = r"""
;(function(){
  var d=document;
  function shrink(file, done){                  /* at most 1600 px and about 500 KB, as JPEG (this also drops location data) */
    var url=URL.createObjectURL(file), img=new Image();
    img.onload=function(){
      var w=img.naturalWidth, h=img.naturalHeight, k=Math.min(1, 1600/Math.max(w,h));
      var c=d.createElement('canvas'); c.width=Math.round(w*k); c.height=Math.round(h*k);
      c.getContext('2d').drawImage(img,0,0,c.width,c.height); URL.revokeObjectURL(url);
      var q=0.82, out=c.toDataURL('image/jpeg',q);
      while(out.length>680000 && q>0.4){ q-=0.12; out=c.toDataURL('image/jpeg',q); }
      done(out.length<=930000 ? out : '');
    };
    img.onerror=function(){ URL.revokeObjectURL(url); done(''); };
    img.src=url;
  }
  function wire(form){
    var file=form.querySelector('[data-photo]'), hidden=form.querySelector('[data-photo-data]'),
        box=form.querySelector('[data-photo-preview]'), note=form.querySelector('[data-media-note]');
    if(file){
      file.addEventListener('change',function(){
        var f=file.files&&file.files[0]; if(!f) return;
        if(!/^image\//.test(f.type)){ note.textContent='Only pictures (screenshots or photos) can be added.'; return; }
        note.textContent='Preparing your screenshot…';
        shrink(f,function(out){
          if(!out){ note.textContent='That picture could not be used. Try a screenshot instead.'; return; }
          hidden.value=out; box.querySelector('img').src=out; box.hidden=false; note.textContent='';
        });
      });
      form.querySelector('[data-photo-remove]').addEventListener('click',function(){ hidden.value=''; file.value=''; box.hidden=true; });
    }
    var mic=form.querySelector('[data-voice]'), Rec=window.SpeechRecognition||window.webkitSpeechRecognition;
    if(mic && Rec){
      mic.hidden=false;
      var area=form.querySelector('[name="'+mic.getAttribute('data-voice')+'"]'), rec=null, base='';
      mic.addEventListener('click',function(){
        if(rec){ rec.stop(); return; }
        rec=new Rec(); rec.lang=navigator.language||'en-IN'; rec.interimResults=true; rec.continuous=true;
        base=area.value ? area.value.replace(/\s*$/,' ') : '';
        rec.onresult=function(e){ var t=''; for(var i=0;i<e.results.length;i++){ t+=e.results[i][0].transcript; } area.value=base+t; };
        rec.onerror=function(e){ note.textContent=e.error==='not-allowed'?'Allow the microphone for this site to use voice.':'Voice stopped: '+e.error+'.'; };
        rec.onend=function(){ rec=null; mic.classList.remove('listening'); mic.querySelector('[data-voice-label]').textContent='Speak'; };
        rec.start(); mic.classList.add('listening'); mic.querySelector('[data-voice-label]').textContent='Stop';
        note.textContent='Listening… check the text before you send it.';
      });
    }
  }
  function scan(root){ Array.prototype.forEach.call((root||d).querySelectorAll('form[data-media]:not([data-media-ready])'),function(f){ f.setAttribute('data-media-ready',''); wire(f); }); }
  scan(); new MutationObserver(function(){ scan(); }).observe(d.documentElement,{childList:true,subtree:true});
})();
"""
