# muse-intiface-bridge
ESP32-S3 伪装成 Lovense Lush，把暮瑟/MuSE 玩具接入 Buttplug/Intiface 标准生态。  ESP32 伪装后 Intiface 可原生识别; 它再把指令翻译成 MuSE 私有协议、用 0x00C7 厂商广播驱动玩具。支持多台设备并联(每板一个设备号)、Windows GUI 控制台、 直发/桥接双通道切换、断线自动重连, 并内置 GUI 烧录工具。  基于 Fi0nee/LS-Buttplug 改造 (非商业许可)。
