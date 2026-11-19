from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
import xml.etree.ElementTree as E
import re,shutil
base=Path('report/figures')
src=base/'source/8-1.drawio'
W,H=440,500;c=canvas.Canvas(str(base/'8-1.pdf'),pagesize=(W,H));c.setTitle('KWT-1 PostNorm encoder - adapted from Berg et al. Figure 2')
f=E.Element('mxfile',host='app.diagrams.net');d=E.SubElement(f,'diagram',name='KWT-1 PostNorm');m=E.SubElement(d,'mxGraphModel',pageWidth=str(W),pageHeight=str(H));r=E.SubElement(m,'root');E.SubElement(r,'mxCell',id='0');E.SubElement(r,'mxCell',id='1',parent='0');counter=0
colors={'blue':'#DFEFFE','purple':'#FCCCDA','yellow':'#DEF6D6','green':'#DEF6D6','white':'#FFFFFF'}
def box(x,y,w,h,text,fill='blue',size=12):
 global counter
 counter+=1;cc=E.SubElement(r,'mxCell',id=str(counter+1),value=text,vertex='1',parent='1',style=f'rounded=1;arcSize=15;fillColor={colors[fill]};strokeColor=#526575;fontFamily=Times New Roman;fontSize={size};');E.SubElement(cc,'mxGeometry',x=str(x),y=str(H-y-h),width=str(w),height=str(h),attrib={'as':'geometry'})
 c.setStrokeColor(HexColor('#526575'));c.setFillColor(HexColor(colors[fill]));c.setLineWidth(1);c.roundRect(x,y,w,h,6,stroke=1,fill=1);c.setFillColor(HexColor('#172332'));c.setFont('Times-Roman',size)
 for i,line in enumerate(text.split('\n')):c.drawCentredString(x+w/2,y+h/2+(len(text.split('\n'))-1)*size*.55-size*.32-i*size*1.1,line)
def arrow(points):
 global counter
 counter+=1;cc=E.SubElement(r,'mxCell',id=str(counter+1),edge='1',parent='1',style='edgeStyle=none;endArrow=block;endSize=7;strokeColor=#526575;strokeWidth=1.3;');g=E.SubElement(cc,'mxGeometry',relative='1',attrib={'as':'geometry'})
 for key,pt in [('sourcePoint',points[0]),('targetPoint',points[-1])]:E.SubElement(g,'mxPoint',x=str(pt[0]),y=str(H-pt[1]),attrib={'as':key})
 if len(points)>2:
  a=E.SubElement(g,'Array',attrib={'as':'points'})
  for x,y in points[1:-1]:E.SubElement(a,'mxPoint',x=str(x),y=str(H-y))
 c.setStrokeColor(HexColor('#526575'));c.setFillColor(HexColor('#526575'));c.setLineWidth(1.3);p=c.beginPath();p.moveTo(*points[0])
 for pt in points[1:]:p.lineTo(*pt)
 c.drawPath(p);x,y=points[-1];a,b=points[-2];dx,dy=x-a,y-b;l=(dx*dx+dy*dy)**.5;dx/=l;dy/=l;p=c.beginPath();p.moveTo(x,y);p.lineTo(x-7*dx+3*dy,y-7*dy-3*dx);p.lineTo(x-7*dx-3*dy,y-7*dy+3*dx);p.close();c.drawPath(p,fill=1)
box(105,20,200,32,'Input X: 99 x 64','green')
box(105,78,200,32,'Single-head attention','purple')
box(187,129,36,26,'+','white',17)
box(105,175,200,30,'LayerNorm 1','yellow')
# Expanded MLP matches the reference PostNorm order.
box(105,232,200,96,'FFN2   256 -> 64\nGELU\nFFN1   64 -> 256','blue',12)
box(187,351,36,26,'+','white',17)
box(105,397,200,30,'LayerNorm 2','yellow')
box(105,455,200,30,'Output Y: 99 x 64','green')
for a,b in [(52,78),(110,129),(155,175),(205,232),(328,351),(377,397),(427,455)]:arrow([(205,a),(205,b)])
arrow([(205,64),(65,64),(65,142),(187,142)])
arrow([(205,218),(45,218),(45,364),(187,364)])
# Annotations remain editable drawio text cells.
for x,y,w,h,text in [(8,160,80,18,'Residual X'),(48,310,55,18,'Residual Z'),(318,83,110,20,'ENC1'),(318,179,110,20,'ENC1'),(318,266,110,20,'FFN'),(318,402,110,20,'ENC1'),(232,210,70,18,'Z: 99 x 64')]:
 counter+=1;cc=E.SubElement(r,'mxCell',id=str(counter+1),value=text,vertex='1',parent='1',style='text;align=center;fontFamily=Times New Roman;fontSize=11;strokeColor=none;fillColor=none;');E.SubElement(cc,'mxGeometry',x=str(x),y=str(H-y-h),width=str(w),height=str(h),attrib={'as':'geometry'});c.setFont('Times-Italic',11);c.setFillColor(HexColor('#526575'));c.drawCentredString(x+w/2,y+h/2-3,text)
c.save();E.ElementTree(f).write(src,encoding='utf-8',xml_declaration=True)