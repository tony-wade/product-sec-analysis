#ifndef __COMMU_BRIDGE_H__
#define __COMMU_BRIDGE_H__			// Include Guard


#include "stdio.h"
#include <stdint.h>
#include <stdbool.h>
#include "main.h"		// for LED



#define RX_SIZE 512


extern uint8_t RxBuffer[RX_SIZE];
extern volatile bool speed_up;

#endif /* __COMMU_BRIDGE_H__ */
