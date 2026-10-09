// 设备身份定义 (独立头文件, 供 LS.h 与 lovense.h 共同包含, 避免循环依赖)
#pragma once

// 设备号由烧录时传入: -DLS_DEVICE_ID=NN (默认 11)
#ifndef LS_DEVICE_ID
#define LS_DEVICE_ID 11
#endif

#define LS_STR_(x) #x
#define LS_STR(x) LS_STR_(x)
// 两级宏展开, 确保 LS_DEVICE_ID 被数值化后再参与字符串拼接
#define LS_DEVICE_NAME "LVS-Lush" LS_STR(LS_DEVICE_ID)

#ifndef DEVICE_NAME
#define DEVICE_NAME LS_DEVICE_NAME
#endif

#ifndef DEVICE_SERVICE
#define DEVICE_SERVICE  "45440001-0023-4BD4-BBD5-A6920E4C5653"
#endif