"""Optional MO2 overlay, written ONLY to task deliverables. Never installs it.

Pins the known Ultra Plus denoiser preset/override differences to its existing
RRClean preset, so switching the game's denoiser does not switch those settings.
"""
from pathlib import Path
import hashlib
import json
import re
import zipfile

base=Path('F:/Ultra Yedek 2/mods/Cyberpunk Ultra Plus/bin/x64/plugins/cyber_engine_tweaks/mods/UltraPlus')
source=base/'config/denoisers.ini'
out=Path('E:/FSRD/sol_batch/21-input-parity')
raw=source.read_bytes()
pattern=re.compile(rb'^\[([^\]\r\n]+)\][ \t]*\r?$',re.M)
matches=list(pattern.finditer(raw))
sections={m.group(1).decode():raw[m.end():matches[i+1].start() if i+1<len(matches) else len(raw)] for i,m in enumerate(matches)}
assert all(key in sections for key in ('RRClean','NRDAMD','NRDDLSS','RREnabled','NRDEnabled'))
replacement={'NRDAMD':sections['RRClean'],'NRDDLSS':sections['RRClean'],
             'NRDEnabled':sections['RREnabled']}
result=bytearray(raw[:matches[0].start()])
for i,m in enumerate(matches):
    name=m.group(1).decode()
    result+=raw[m.start():m.end()]+replacement.get(name,sections[name])
result=bytes(result)
newmatches=list(pattern.finditer(result))
newsections={m.group(1).decode():result[m.end():newmatches[i+1].start() if i+1<len(newmatches) else len(result)] for i,m in enumerate(newmatches)}
assert newsections['NRDAMD']==newsections['NRDDLSS']==newsections['RRClean']
assert newsections['NRDEnabled']==newsections['RREnabled']
for name in sections:
    if name not in replacement:assert sections[name]==newsections[name]
assert result.count(b'\r\n')==result.count(b'\n')
relative=Path('bin/x64/plugins/cyber_engine_tweaks/mods/UltraPlus/config/denoisers.ini')
target=out/'optional-ultraplus-control'/relative
target.parent.mkdir(parents=True,exist_ok=True)
target.write_bytes(result)
readme='''OPTIONAL CONTROL ONLY / ISTEGE BAGLI KONTROL

MO2 ile ayri bir mod olarak kur; Cyberpunk Ultra Plus'tan sonra kazansin.
Ultra Plus'ta RRClean sec. Iki oyun-denoiser modunda da ayni preset degerleri
ve RR override'lari kullanilir. Oyunu yeniden baslat.

Ilk olcek A/B testini mevcut mod kurulumunla yap. Bu katmani sonra, ayri bir
deney olarak ac. Geri donmek icin MO2'de yalniz bu modu kapat.

Bu katman oyunun RR acikken gercek NRD ham tamponlari uretmesini saglamaz.
Yalniz bu kurulu Ultra Plus surumunun bilinen denoiser-ayar farklarini sabitler.
Baska modlarin/oyunun farklarini kaldirdigi veya kaliteyi duzelttigi iddia edilmez.

No DLL is included. This overlay has not been tested in the running game.
'''
(out/'optional-ultraplus-control/README.txt').write_text(readme,encoding='utf-8')
with zipfile.ZipFile(out/'UltraPlus_Input_Parity_Optional.zip','w',zipfile.ZIP_DEFLATED) as archive:
    archive.writestr(relative.as_posix(),result)
    archive.writestr('README.txt',readme)
manifest={'source':str(source),'source_sha256':hashlib.sha256(raw).hexdigest(),
    'engine_lua_sha256':hashlib.sha256((base/'lib/Engine.lua').read_bytes()).hexdigest(),
    'output_sha256':hashlib.sha256(result).hexdigest(),
    'section_replacements':{'NRDAMD':'RRClean','NRDDLSS':'RRClean','NRDEnabled':'RREnabled'},
    'unchanged_other_sections':True,'crlf_preserved':True,'installed':False,'in_game_verified':False}
(out/'ultraplus-control.json').write_text(json.dumps(manifest,indent=2))
print(out/'UltraPlus_Input_Parity_Optional.zip')
