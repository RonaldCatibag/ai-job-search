#!/usr/bin/env python3
"""Build three Diether-style resume PDFs from the confirmed JSON source."""
from pathlib import Path
import json, argparse
from html import escape
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
import pymupdf
ROOT=Path(__file__).resolve().parents[1]
W,H=612,792
LEFT,RIGHT=46.8,46.8
WIDTH=W-LEFT-RIGHT
NAVY=HexColor("#203F66");BLUE=HexColor("#2368AA");INK=HexColor("#263449");MUTED=HexColor("#6B7E96")
FONTDIR=Path("/mnt/c/Windows/Fonts")
for name,file in [("CV","calibri.ttf"),("CV-Bold","calibrib.ttf")]:pdfmetrics.registerFont(TTFont(name,str(FONTDIR/file)))
pdfmetrics.registerFontFamily("CV",normal="CV",bold="CV-Bold")
STYLE=ParagraphStyle("body",fontName="CV",fontSize=9.5,leading=12.5,textColor=INK,spaceAfter=0)
class Resume:
 def __init__(self,path,title):
  self.c=canvas.Canvas(str(path),pagesize=(W,H));self.c.setTitle("Ronald Catibag - "+title);self.c.setAuthor("Ronald Catibag");self.y=H-48;self.page=1;self.boxes=[]
 def paragraph(self,text,indent=0,size=9.5,leading=12.5,gap=5):
  style=ParagraphStyle("p",parent=STYLE,fontSize=size,leading=leading)
  p=Paragraph(text,style);_,height=p.wrap(WIDTH-indent,700)
  if self.y-height<43:raise ValueError(f"Content overflow on page {self.page}: {text[:70]}")
  p.drawOn(self.c,LEFT+indent,self.y-height);self.boxes.append((self.page,LEFT+indent,self.y-height,self.y));self.y-=height+gap
 def bullet(self,label,body):
  self.c.setFillColor(INK);self.c.setFont("CV-Bold",9.5);self.c.drawString(LEFT+9,self.y-9,"•")
  self.paragraph("<b>"+escape(label)+":</b> "+escape(body),indent=19,gap=5)
 def section(self,title):
  self.y-=11;self.c.setFillColor(NAVY);self.c.setFont("CV-Bold",12);self.c.drawString(LEFT,self.y-11,title.upper());self.y-=21
  self.c.setStrokeColor(NAVY);self.c.setLineWidth(1);self.c.line(LEFT,self.y,W-RIGHT,self.y);self.y-=8
 def job_header(self,job,continued=False):
  self.paragraph("<b>"+escape(job['role'])+" | <font color='#2368AA'>"+escape(job['company'])+(" (continued)" if continued else "")+"</font></b>",size=10.5,leading=13,gap=3)
  self.paragraph(escape(job['dates']),size=9,leading=11,gap=7)
 def job(self,job):
  self.job_header(job)
  for label,body in job['bullets']:self.bullet(label,body)
 def bullet_height(self,label,body):
  p=Paragraph('<b>'+escape(label)+':</b> '+escape(body),STYLE);return p.wrap(WIDTH-19,700)[1]+5
 def next_page(self):self.c.showPage();self.page+=1;self.y=H-48
 def finish(self):self.c.save()
def build(data,key,out):
 v=data['variants'][key];path=out/f"Ronald_Catibag_{key}_2026.pdf";r=Resume(path,v['headline']);c=r.c
 c.setFillColor(NAVY);c.setFont("CV-Bold",22);c.drawCentredString(W/2,r.y-18,data['name']);r.y-=40
 c.setFillColor(BLUE);c.setFont("CV-Bold",11);c.drawCentredString(W/2,r.y,v['headline']);r.y-=18
 c.setFillColor(INK);c.setFont("CV",9);c.drawCentredString(W/2,r.y,data['phone']+"  |  "+data['email']+"  |  "+data['location']);r.y-=14
 links=[data['linkedin']]
 if data.get('github'):links.append(data['github'].removeprefix('https://').removeprefix('http://'))
 line='  |  '.join(links);x=(W-pdfmetrics.stringWidth(line,'CV',9))/2
 c.setFillColor(BLUE);c.drawCentredString(W/2,r.y,line)
 for link in links:
  width=pdfmetrics.stringWidth(link,'CV',9);c.linkURL('https://'+link,(x,r.y-2,x+width,r.y+9),relative=0);x+=width+pdfmetrics.stringWidth('  |  ','CV',9)
 r.y-=6
 r.section("Professional Summary");r.paragraph(escape(v['summary']),size=10,leading=13,gap=2)
 r.section("Technical Skills")
 skills=list(data['skills'])
 if key=='devops':skills.sort(key=lambda x:0 if x[0]=='Infrastructure & Delivery' else 1)
 if key=='platform_engineer':skills.sort(key=lambda x:0 if x[0] in ['Infrastructure & Delivery','AI & Enablement'] else 1)
 for label,body in skills:r.bullet(label,body)
 r.section("Professional Experience");r.job_header(data['current'])
 for label,body in data['current']['bullets']:
  if r.y-r.bullet_height(label,body)<43:
   r.next_page();r.section("Professional Experience - Continued");r.job_header(data['current'],continued=True)
  r.bullet(label,body)
 if r.page==1:
  r.next_page();r.section("Professional Experience - Continued")
 for j in data['previous']:r.job(j);r.y-=6
 r.section("Selected Personal Projects")
 for label,body in data['personal']:r.bullet(label,body)
 r.section("Education")
 for degree,school,dates in data['education']:r.paragraph("<b>"+escape(degree)+"</b> | "+escape(school)+" | "+escape(dates),gap=6)
 r.section("Certification");r.paragraph(escape(data['certification']))
 r.finish()
 # Parseability, page count and geometry checks on the finished PDF.
 doc=pymupdf.open(path);text="\n".join(p.get_text() for p in doc)
 assert len(doc)==2,(path,len(doc))
 for required in ['RONALD CATIBAG','Tookitaki','July 2026 - Present','June 2024 - July 2026','Datadog','CrowdStrike','MCP','RAG','SLAs','SLOs','SLIs',data['email'],data['phone']]:assert required in text,(path,required)
 assert not any(x in text for x in ['DIETHER','Pom arijos','Accenture','Maya PH','DataCamp','�','(cid:'])
 for page in doc:
  for word in page.get_text('words'):assert word[0]>=40 and word[2]<=W-39 and word[1]>=35 and word[3]<=H-35,(path,word)
 preview=ROOT/'tmp/pdfs/resume-preview'/key;preview.mkdir(parents=True,exist_ok=True)
 for i,page in enumerate(doc):page.get_pixmap(matrix=pymupdf.Matrix(1.3,1.3)).save(str(preview/f'page-{i+1}.png'))
 md=['# '+data['name'],v['headline'],data['phone']+' | '+data['email']+' | '+data['location'],' | '.join(links),'','## Professional Summary',v['summary'],'','## Technical Skills']
 md += ['- **'+label+':** '+body for label,body in skills]
 md += ['','## Professional Experience']
 for job in [data['current']]+data['previous']:
  md += ['','### '+job['role']+' | '+job['company'],job['dates']]+['- **'+label+':** '+body for label,body in job['bullets']]
 md += ['','## Selected Personal Projects']+['- **'+label+':** '+body for label,body in data['personal']]
 md += ['','## Education']+[' | '.join(x) for x in data['education']]+['','## Certification',data['certification']]
 path.with_suffix('.md').write_text('\n'.join(md)+'\n')
 print(json.dumps({'pdf':str(path),'pages':len(doc),'text_checks':'passed','geometry_checks':'passed','preview':str(preview)}))
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,default=ROOT/'cv/ronald_resume_2026-11-09.json');ap.add_argument('--out',type=Path,default=ROOT/'output/pdf');a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 data=json.loads(a.source.read_text())
 for key in data['variants']:build(data,key,a.out)
if __name__=='__main__':main()
