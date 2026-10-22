"""Original WFCompanion compass artwork and geometric installer layout."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def render(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    icon=Image.open(Path(__file__).parent/'public_art/wfcompanion-compass.png').convert('RGBA')
    icon.thumbnail((256,256),Image.Resampling.LANCZOS)
    icon.save(folder/'forever.png');icon.save(folder/'forever.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    canvas=Image.new('RGB',(994,720),'#111b24');d=ImageDraw.Draw(canvas)
    for inset,color in [(4,'#564b31'),(10,'#dfbd70'),(15,'#314957')]:
        d.rectangle((inset,inset,993-inset,719-inset),outline=color,width=2)
    canvas.save(folder/'wizard-background.png')
    panel=Image.new('RGB',(328,720),'#142a36');panel.paste(icon,(36,80),icon)
    d=ImageDraw.Draw(panel)
    font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',28)
    d.text((164,375),'WFCompanion',font=font,anchor='mm',fill='#dfbd70')
    font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',17)
    for y,line in [(450,'Your characters.'),(478,'Your adventures.'),(506,'Always within reach.')]:
        d.text((164,y),line,font=font,anchor='mm',fill='#e5eef1')
    panel.save(folder/'wizard-sidebar.png')
    (folder/'SOURCES.md').write_text('Original WFCompanion compass generated with OpenAI image generation; see public_art/README.md. Geometric layout by WFCompanion. Text rendered using installed Windows Segoe UI; no font files are included.\n')
