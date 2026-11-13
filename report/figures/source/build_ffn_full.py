from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
import xml.etree.ElementTree as E
import shutil,re
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
p=Path('report/figures')
W,H=920,480;c=canvas.Canvas(str(p/'ffn-full.pdf'),pagesize=(W,H));c.setTitle('Complete FFN and block-local activation memory')
f=E.Element('mxfile',host='app.diagrams.net');d=E.SubElement(f,'diagram',name='Complete FFN');m=E.SubElement(d,'mxGraphModel',pageWidth=str(W),pageHeight=str(H));root=E.SubElement(m,'root');E.SubElement(root,'mxCell',id='0');E.SubElement(root,'mxCell',id='1',parent='0');n=1
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

label('(a) Complete FFN: 64 -> 256 -> 64',15,449,890,18,True)
box('LN1 input\n99 × 64\nINT16',20,310,115,85,'blue')
box('FFN1\n64 -> 256\nINT40 output',170,310,120,85,'blue')
box('Fixed-point GELU\nRNE + saturation\nINT16 output',325,310,145,85,'pink',14)
box('Activation\nSRAM\nINT16',505,310,115,85,'yellow')
box('FFN2\n256 -> 64\nINT40 output',655,310,120,85,'blue')
box('Result FIFO\n99 × 64\n40-bit to ENC1',810,310,100,85,'green',13)
for a,b in [(135,170),(290,325),(470,505),(620,655),(775,810)]:arrow([(a,352),(b,352)])
label('W1: 64 × 256; b1: 256',130,416,200,14)
arrow([(230,416),(230,395)],'#9E6D29')
label('W2: 256 × 64; b2: 64',615,416,200,14)
arrow([(715,416),(715,395)],'#9E6D29')
label('(b) Physical storage: reuse one 8-row activation block',15,223,890,18,True)
box('Even bank\n1,024 × 16 bits',220,140,210,55,'yellow',15)
box('Odd bank\n1,024 × 16 bits',470,140,210,55,'yellow',15)
label('2 banks × 1,024 × 16 bits = 8 × 256 INT16 = 4 KiB',80,106,760,15)
box('GELU writes\ncurrent row block',100,40,200,48,'pink',14)
box('FFN2 reads\n256-term reduction',360,40,200,48,'blue',14)
box('Release and reuse\nfor the next row block',620,40,200,48,'green',14)
arrow([(300,64),(360,64)]);arrow([(560,64),(620,64)])
c.save();E.ElementTree(f).write(p/'source/ffn-full.drawio',encoding='utf-8',xml_declaration=True)