from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
import xml.etree.ElementTree as E
import shutil,re
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
p=Path('report/figures')
W,H=920,480;c=canvas.Canvas(str(p/'7-2.pdf'),pagesize=(W,H));c.setTitle('Single-head attention and row-cache reuse')
f=E.Element('mxfile',host='app.diagrams.net');d=E.SubElement(f,'diagram',name='Single-head attention');m=E.SubElement(d,'mxGraphModel',pageWidth=str(W),pageHeight=str(H));root=E.SubElement(m,'root');E.SubElement(root,'mxCell',id='0');E.SubElement(root,'mxCell',id='1',parent='0');n=1
cols={'blue':'#BBD5F1','green':'#C4E3BA','yellow':'#D9E9F8','pink':'#E7A8BC','white':'#FFFFFF'}
def htmltext(text):
 text=re.sub(r'([Qsp])_i',r'\1<sub>i</sub>',text)
 text=text.replace('K^T','K<sup>T</sup>').replace('1 / sqrt(64)','1 / √64').replace(' x ',' × ')
 return text
def drawtext(text,x,y,w,size=15):
 if text=='1 / sqrt(64)':
  c.setFont('Times-Roman',size);left=x+w/2-31;c.drawString(left,y,'1 /')
  z=left+22;path=c.beginPath();path.moveTo(z,y+5);path.lineTo(z+3,y+7);path.lineTo(z+6,y-1);path.lineTo(z+11,y+size-2);path.lineTo(z+30,y+size-2);c.setStrokeColor(HexColor('#102D43'));c.setLineWidth(.9);c.drawPath(path);c.drawString(z+13,y,'64');return
 para=Paragraph(htmltext(text),ParagraphStyle('math',fontName='Times-Roman',fontSize=size,leading=size*1.15,alignment=1,textColor=HexColor('#102D43')))
 _,height=para.wrap(w,100);para.drawOn(c,x,y-size*.18)
def cell(text,x,y,w,h,style):
 global n
 n+=1;a=E.SubElement(root,'mxCell',id=str(n),value=htmltext(text).replace('\n','<br>'),vertex='1',parent='1',style=style+'html=1;');E.SubElement(a,'mxGeometry',x=str(x),y=str(H-y-h),width=str(w),height=str(h),attrib={'as':'geometry'})
def label(text,x,y,w=200,size=14,bold=False):
 cell(text,x,y,w,20,f'text;align=center;fontFamily=Times New Roman;fontSize={size};fontStyle={1 if bold else 0};strokeColor=none;fillColor=none;')
 c.setFillColor(HexColor('#102D43'));c.setFont('Times-Bold' if bold else 'Times-Roman',size);c.drawCentredString(x+w/2,y+5,text)
def box(text,x,y,w,h,col='blue',size=15):
 cell(text,x,y,w,h,f'rounded=1;arcSize=15;fillColor={cols[col]};strokeColor=#3E5E76;fontFamily=Times New Roman;fontSize={size};')
 c.setStrokeColor(HexColor('#3E5E76'));c.setFillColor(HexColor(cols[col]));c.setLineWidth(1);c.roundRect(x,y,w,h,7,stroke=1,fill=1)
 lines=text.split('\n');c.setFillColor(HexColor('#102D43'));c.setFont('Times-Roman',size)
 for j,line in enumerate(lines):drawtext(line,x,y+h/2+(len(lines)-1)*size*.58-size*.3-j*size*1.16,w,size)
def arrow(points,col='#426B88',dash=False):
 global n
 n+=1;a=E.SubElement(root,'mxCell',id=str(n),edge='1',parent='1',style=f'edgeStyle=none;endArrow=block;endSize=8;strokeColor={col};strokeWidth=1.5;dashed={int(dash)};');g=E.SubElement(a,'mxGeometry',relative='1',attrib={'as':'geometry'})
 for key,pt in [('sourcePoint',points[0]),('targetPoint',points[-1])]:E.SubElement(g,'mxPoint',x=str(pt[0]),y=str(H-pt[1]),attrib={'as':key})
 if len(points)>2:
  z=E.SubElement(g,'Array',attrib={'as':'points'})
  for x,y in points[1:-1]:E.SubElement(z,'mxPoint',x=str(x),y=str(H-y))
 c.saveState();c.setStrokeColor(HexColor(col));c.setFillColor(HexColor(col));c.setLineWidth(1.5)
 if dash:c.setDash(5,4)
 q=c.beginPath();q.moveTo(*points[0])
 for pt in points[1:]:q.lineTo(*pt)
 c.drawPath(q);c.setDash();x,y=points[-1];a,b=points[-2];dx,dy=x-a,y-b;l=(dx*dx+dy*dy)**.5;dx/=l;dy/=l;q=c.beginPath();q.moveTo(x,y);q.lineTo(x-8*dx+3.5*dy,y-8*dy-3.5*dx);q.lineTo(x-8*dx-3.5*dy,y-8*dy+3.5*dx);q.close();c.drawPath(q,fill=1);c.restoreState()
label('(a) Single-head attention: logical computation',15,449,890,18,True)
box('Q / K / V\nprojection\nEach: 99 x 64',20,325,140,82)
box('MatMul\nQ K^T\n99 x 99',205,325,110,82)
box('Scale\n1 / sqrt(64)\n= 1 / 8',360,325,110,82,'yellow')
box('Row\nSoftmax\nP: 99 x 99',515,325,110,82,'green')
box('MatMul\nP V\n99 x 64',670,325,100,82)
box('Output\nprojection\n99 x 64',805,325,100,82)
for a,b in [(160,205),(315,360),(470,515),(625,670),(770,805)]:arrow([(a,366),(b,366)])
label('Q, K',160,374,45,12)
arrow([(90,325),(90,288),(720,288),(720,325)],'#388774');label('V: 99 x 64',320,288,180,14)
label('S and P are logical matrices; hardware processes one query row at a time.',20,249,885,14)
label('(b) Physical execution: reuse one 128 x 32-bit row cache',15,206,890,18,True)
box('Query Q_i\nAll 99 keys',20,88,135,65)
box('Scores s_i\n99 entries',205,88,145,65,'yellow')
box('Exponentials\n99 entries',380,88,145,65,'pink')
box('Probabilities p_i\n99 entries',555,88,150,65,'green')
box('Weighted sum\np_i V\n64 features',755,88,150,65)
for a,b in [(155,205),(350,380),(525,555),(705,755)]:arrow([(a,120),(b,120)])
label('Same cache addresses: scores -> exponentials -> probabilities',175,158,550,14)
arrow([(830,88),(830,36),(87,36),(87,88)],dash=True)
label('After the weighted sum, overwrite the cache for query i + 1',180,39,550,14)
label('Q, K and V remain in separate vector memories.',200,7,520,13)
c.save();E.ElementTree(f).write(p/'source/7-2.drawio',encoding='utf-8',xml_declaration=True)