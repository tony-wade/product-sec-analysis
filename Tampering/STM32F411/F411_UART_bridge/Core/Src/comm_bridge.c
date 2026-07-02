#include "commu_bridge.h"
#include "stm32f4xx_hal.h"

extern UART_HandleTypeDef huart1; 	// import value from main.c


uint8_t RxBuffer[RX_SIZE];


// special seq set for speed up
const uint8_t RX_SpeedUpSeq[] = {0x89, 0x42, 0x0, 0x2a, 0x0, 0x0, 0x14, 0xec, 0x8a};
const uint16_t RX_SpeedUpSeq_Size = sizeof(RX_SpeedUpSeq);


typedef struct{
    const uint8_t *cond;
    uint16_t  cond_size;
    const uint8_t *data;
    uint16_t  data_size;
} Trigger_t;


// overwrite sequence sets. Note that ARM don't have "xdata", just const or not.
__ALIGNED(8) const uint8_t cond_A[] = {0x89, 0x82, 0xA0, 0x0, 0xA0, 0x0, 0x91, 0x5b, 0x8A}; // is ptr already
__ALIGNED(8) const uint8_t cond_B[] = {0x89, 0x42, 0x0, 0x0, 0x73, 0xcd, 0x8a};


const uint8_t data_A[] = {
    0x89, 0x2, 0x0, 0x0, 0x0, 0x0, 0x0, 0x0,0x2,0x10,0x0,0x0,
    0x0,0x2,0x0,0x0,0x80,0x0,0x20,0x0,0x0,0x0,0x0,0x0,0x0,0x0,
    0x0,0x0,0x60,0x80,0x50,0x0,0x40,0x0,0x0,0x0,0x42,0x42,0x0,
    0x0,0x0,0x0,0x80,0x0,0x64,0x0,0x4,0x0,0x60,0x02,0x40,0x0,
    0xf0,0x4f,0x8a
};

const uint8_t data_B[] = {0x89,0x82,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x0,0x64,
    0x0,0x4,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80
    ,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80
    ,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80,0x0,0x80,
    0x0,0x49,0xa6,0x8a
};

const Trigger_t trigger_table[] = {
    {cond_A, sizeof(cond_A), data_A, sizeof(data_A)},
    {cond_B, sizeof(cond_B), data_B, sizeof(data_B)},
};

#define TRIGGER_SIZE  (sizeof(trigger_table) / sizeof(Trigger_t)) 	// trigger_table element


volatile bool speed_up = 0;
volatile uint8_t trigger_idx = 0;
volatile bool is_target = 0;
volatile uint16_t prev_size = 0;		// previous position in DMA buffer
volatile uint16_t len = 0;			// packet length
volatile uint16_t table_crc16;
volatile uint16_t rx_crc16;

/*
 * HAL_func's structure is fixed!  it'll automatically be called by handler.
 */


// External interrupt
void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
	if (is_target){
		// disable EXTI from pin11 until sending finished
		HAL_NVIC_DisableIRQ(EXTI15_10_IRQn);

		// send uart from dma
		HAL_UART_Transmit_DMA(&huart1, trigger_table[trigger_idx].data, (uint16_t)trigger_table[trigger_idx].data_size);

		is_target = 0;
		return;
	}

	// PA11 -> PA8
	//else if (GPIO_Pin == GPIO_PIN_11)  // if multiple GPIO_Pin have EXTI
	else
	{
		if (GPIOA->IDR & GPIO_PIN_11){			// read
			GPIOA->BSRR = GPIO_PIN_8;			// high
		}else{
			GPIOA->BSRR = (GPIO_PIN_8 << 16);	// low
		}
	}
}


// RX callback for IDLE,HT,TC INT
void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size)
{
	//if (huart->Instance == USART1)

	if (trigger_idx >= TRIGGER_SIZE) {	// trigger complete
        return;
    }
    if (huart->RxEventType != HAL_UART_RXEVENT_IDLE){				// only IDLE INT
    	return;
    }

    // Size = current shift from buffer[0]
    if (prev_size < Size){
    	len = Size - prev_size;
    }else if (prev_size > Size){
    	len = (RX_SIZE - prev_size) + Size;
    }else{
    	return;			// beware overflow error
    }
    prev_size = Size;	// Load for next time


    if (speed_up == 0){
    	if (len == RX_SpeedUpSeq_Size){
    		speed_up = 1;
    		prev_size = 0; // restart
    	}
    	return;
    }

	if (len == trigger_table[trigger_idx].cond_size){			// fast matching
		//HAL_GPIO_WritePin(LED_GPIO_Port, LED_Pin, GPIO_PIN_SET);		// OFF
		HAL_GPIO_WritePin(LED_GPIO_Port, LED_Pin, GPIO_PIN_RESET);		// ON
		// Memory readout in ARM is LSB!
        rx_crc16 = ((uint16_t)RxBuffer[((Size-2) + RX_SIZE) % RX_SIZE] << 8) | RxBuffer[((Size-3) + RX_SIZE) % RX_SIZE];  // to lsb
        table_crc16 = *(uint16_t *)&(trigger_table[trigger_idx].cond[len - 3]);		// crc16 + 0x8a

        if (rx_crc16 == table_crc16){
        	is_target = 1;
        }
	}
}

// TX complete callback
void HAL_UART_TxCpltCallback (UART_HandleTypeDef *huart)
{
	if (huart->Instance == USART1)
	{
		trigger_idx += 1;	// next

        // clear undesired interrupt flag, be aware to the reset method
		EXTI->PR = GPIO_PIN_11;

		// enable EXTI
		HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);
	}
}





