import copy, json, sys, subprocess, os, re
from pptx import Presentation
from pptx.util import Inches, Emu, Pt
from pptx.enum.text import MSO_AUTO_SIZE
from lxml import etree

TPL = sys.argv[1]; OUT = sys.argv[2]; SRC = sys.argv[3]
place = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None

prs = Presentation(TPL)
sl = prs.slides[0]
sh = {s.name: s for s in sl.shapes}
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'

def set_par_text(p_el, text, bold=None, size=None, color=None):
    runs = p_el.findall(A + 'r')
    for r in runs[1:]:
        p_el.remove(r)
    r = runs[0]
    r.find(A + 't').text = text
    rpr = r.find(A + 'rPr')
    if bold is not None:
        rpr.set('b', '1' if bold else '0')
    if size is not None:
        rpr.set('sz', str(int(size * 100)))
    # drop any extra elements like a:br / fields
    for el in list(p_el):
        if el.tag in (A + 'br', A + 'fld'):
            p_el.remove(el)
    return p_el

def fill(shape, blocks, heading_idx=0, body_idx=2):
    """blocks: list of ('h', text) | ('p', text) | ('blank', n)"""
    tf = shape.text_frame
    txBody = tf._txBody
    pars = txBody.findall(A + 'p')
    h_t = copy.deepcopy(pars[heading_idx]); b_t = copy.deepcopy(pars[body_idx])
    for p in pars:
        txBody.remove(p)
    first = True
    for kind, val in blocks:
        if kind == 'h':
            p = set_par_text(copy.deepcopy(h_t), val)
            if first:  # no space before the very first heading
                pass
            txBody.append(p)
        elif kind == 'p':
            txBody.append(set_par_text(copy.deepcopy(b_t), val))
        elif kind == 'blank':
            for _ in range(val):
                txBody.append(set_par_text(copy.deepcopy(b_t), ' '))
        first = False
    tf.auto_size = MSO_AUTO_SIZE.NONE

c = json.load(open(os.path.join(SRC, 'content.json')))

# Title box: title, names, guide
t = sh['AutoShape 1']; tp = t.text_frame._txBody.findall(A + 'p')
set_par_text(tp[0], c['title']); set_par_text(tp[1], c['names']); set_par_text(tp[2], c['guide'])
t.text_frame.auto_size = MSO_AUTO_SIZE.NONE

# Geometry (space management): shorter abstract box, taller left column
ab = sh['AutoShape 2']; left = sh['AutoShape 3']; right = sh['AutoShape 4']
ab.height = Inches(c['abstract_h'])
gap = Inches(0.25)
left.top = ab.top + ab.height + gap
left.height = Emu(right.top + right.height - left.top)

fill(ab, [('h', 'Abstract'), ('p', c['abstract'])])
fill(left, c['left'])
fill(right, c['right'])

if place:
    for shp in (left, right):
        for t in shp.text_frame._txBody.iter(A + 't'):
            if t.text and t.text.startswith('@@'):
                t.text = ' '
    for img, x, y, w in place:
        sl.shapes.add_picture(os.path.join(SRC, img), Inches(x), Inches(y), width=Inches(w))
if place:
    from pptx.enum.text import PP_ALIGN
    cap = c.get('qr_caption')
    if cap:
        x, y, w = cap['x'], cap['y'], cap['w']
        tb = sl.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(0.5))
        p = tb.text_frame.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); r.text = cap['text']; r.font.name = 'Bookman Old Style'; r.font.size = Pt(14); r.font.bold = True
        tb.text_frame.word_wrap = True
prs.save(OUT)
