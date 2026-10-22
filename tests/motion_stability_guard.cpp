#include "OptiScaler/shaders/fsrd_preprocess/FSRDNrdTemporalControl.h"
#include <cassert>
#include <limits>
int main() {
 NrdBridge::MotionStabilitySettings s;
 const float nan=std::numeric_limits<float>::quiet_NaN();
 const float inf=std::numeric_limits<float>::infinity();
 assert(NrdBridge::NextMotionStability(s,nan,true,0,0)==s.moving);
 assert(NrdBridge::NextMotionStability(s,inf,true,0,0)==s.moving);
 assert(NrdBridge::NextMotionStability(s,0.7f,true,-0.1f,0)==s.moving);
 assert(NrdBridge::NextMotionStability(s,0.7f,true,0,-0.1f)==s.moving);
 assert(NrdBridge::NextMotionStability(s,0.7f,true,0,0)>0.7f);
}
