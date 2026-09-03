rm -rf achillies
cd ~
git clone https://github.com/VSEJGFB/achillies.git 
cd achillies
git submodule init
git submodule update
(cd salticidae; cmake . -DCMAKE_INSTALL_PREFIX=.; make; make install)

