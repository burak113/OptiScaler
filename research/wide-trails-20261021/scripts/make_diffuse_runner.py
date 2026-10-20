import sys
from pathlib import Path
sys.path.insert(0,'F:/OptiRevelations/OSA-27-astra-audit/OptiScaler/shaders/shader_tools')
from fsrd_toolchain import compile_cpp
O=Path(__file__).parent
s=Path('E:/FSRD/rrlab/runner/rrlab_runner.cpp').read_text()
assert 'if(splitCost)create.signalFlags=FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE;' in s
s=s.replace('if(splitCost)create.signalFlags=FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE;','create.signalFlags=FFX_DENOISER_SIGNAL_DIRECT_DIFFUSE; // Task32: diffuse-only NN/exposure context.')
assert 'diffuse.header.pNext = &specular.header;' in s
s=s.replace('diffuse.header.pNext = &specular.header;','diffuse.header.pNext = nullptr; // No specular dispatch in this isolated context.')
s=s.replace('for (unsigned i = 7; i < 9; ++i)', 'for (unsigned i = 7; i < 8; ++i)')
needle='        for (unsigned i = 7; i < 8; ++i) {\n            auto& t = tex[i]; char* mapped'
assert needle in s
s=s.replace(needle,'        std::vector<char> unusedSpec(size_t(w)*h*8,0); outS.write(unusedSpec.data(),unusedSpec.size());\n'+needle)
(O/'rrlab_diffuse.cpp').write_text(s)
compile_cpp(O/'rrlab_diffuse.cpp',O/'rrlab_diffuse.exe',['d3d12.lib','dxgi.lib','bcrypt.lib'],[])
print('Compiled diffuse-only experimental runner; specular output is unused')
