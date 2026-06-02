##
## This file is part of the libsigrokdecode project.
##
## Copyright (C) 2011 Gareth McMullin <gareth@blacksphere.co.nz>
## Copyright (C) 2012-2014 Uwe Hermann <uwe@hermann-uwe.de>
## Copyright (C) 2022 DreamSourceLab <support@dreamsourcelab.com>
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, see <http://www.gnu.org/licenses/>.
##
 
## text block fill color table:
##  [#EF2929,#F66A32,#FCAE3E,#FBCA47,#FCE94F,#CDF040,#8AE234,#4EDC44,#55D795,#64D1D2
##  ,#729FCF,#D476C4,#9D79B9,#AD7FA8,#C2629B,#D7476F]
 
import sigrokdecode as srd

class ModeError(Exception):
    pass

class ChannelError(Exception):
    pass


# 协议模块类
class Decoder(srd.Decoder): 

    # 说明需要安装的python版本
    api_version = 3

    # 协议标识，必须唯一，这里我们用"example"给协议命名
    id = 'pulse-based'

    # 协议名称, 不一定要求跟标识一致
    name = 'Pulse-based' 
    longname = 'Pulse-based protocol decoder'
 
    desc = 'a scalable decoder for Pulse-based protocol'
 
    license = 'gplv2+' 
    inputs = ['logic'] 
    outputs = []
 
    tags = ['Encoding']
 
    channels = (
        {'id': 'data', type: -1, 'name': 'Data', 'desc': 'Data line'},
    )
 
    optional_channels = (
        {'id': 'ref', type: -1, 'name': 'Reference', 'desc': 'reference line for certain protocol'},
    )

    # 提供给用户通过界面设置的参数，根据业务需要来定义
    # 通过self.options[id]取值，id就是各个项的id值，比如下面的"wordsize"
    options = ( 
        {'id': 'mode', 'desc': 'Specific protocol structure', 'default': 'none', 
            'values': ('HP', 'none')},
        {'id': 'polarity', 'desc': 'Polarity', 'default': 'active-high',
            'values': ('active-low', 'active-high')}, 

        {'id': 'reverse_bit', 'desc': 'reverse binary-level definition', 'default': False,
            'values': (False, True)}, 
        {'id': 'threshold', 'desc': 'the threshold(percentage) to duty cycle', 'default': 50,
            'values': tuple(range(1,99,1))},
     )

    # 解析结果 项定义
    # annotations里的每一项可以有2到3个属性，当有３个属性时，第一个表示类型
    # 类型对应0-16个颜色，当类型范围在200-299时，将绘制边沿箭头
    annotations = (
        ('0', 'start', 'Start condition'),   # 顯示id 
        ('1', 'cmd', 'CMD'),        
        ('2', 'length', 'Byte length of the data'),
        ('222', 'data', 'Data'), 
        ('3', 'crc', 'CRC'),
        ('4', 'stuffing', 'charging...etc'),
        ('5', 'stop', 'Stop condition'), 
        
        ('6', 'duty-cycle', 'Duty cycle'), 
    )

    # 解析结果 行定义
    # 有put輸出之annotations皆要定義
    annotation_rows = ( 
        ('control', 'Control', (0,6)),
        ('cmd', 'CMD', (1,)),
        ('len', 'LEN', (2,)),
        ('data', 'Data', (3,)),  # idx = 4th         
        ('crc', 'CRC', (4,)),
  
        ('duty-cycle', 'Duty cycle', (7,)), 
    )

 
    # 构造函数，自动被调用
    def __init__(self): 
        self.reset()

    # 重置函数，在这里做一些重置和定义类私有变量工作
    def reset(self): 
        self.samplerate = None
        self.threshold = None
        self.bit_def = None
        self.ss_block = self.es_block = None  # bit start / end idx 
        self.ss_byte = self.es_byte= None  # bytes start / end idx 
        self.len = 0  
        self.databytes = []
        self.state = 'FIND START'
        self.is_response_flag = False 
        

    #  獲取取樣率, 自動呼叫
    def metadata(self, key, value):
        if key == srd.SRD_CONF_SAMPLERATE:
            self.samplerate = value

    
   
  
    # 开始执行解码任务时，由c底层代码自动调用一次
    # 这里，完成一些解码结果项annotation类型的注册
    # 类型有: OUTPUT_ANN，OUTPUT_PYTHON，OUTPUT_BINARY，OUTPUT_META
    # self.register函数是c底层类提供的
    # OUTPUT_ANN: 將解析出的資料直接顯示於螢幕
    def start(self):
        self.out_ann = self.register(srd.OUTPUT_ANN)
        self.out_binary = self.register(srd.OUTPUT_BINARY)
        self.threshold = self.options['threshold']    # instance建立後才有.options
        self.bit_def = self.options['reverse_bit']  
        self.hp_mode = bool(self.options['mode'] == 'HP')
  


    # 定义一个输出函数
    # a,b为采样位置的起点和终点
    # ann为annotations定义的项序号, 不可跳號
    # data是一个列表，列表里有１到３个字符串，它们将显示到屏幕
    # annotation输出到哪一行由annotation_rows决定
    # self.out_ann就是上面注册的消息类型了
    # self.put是c底层类提供的函数
    def put_ann(self, a, b, ann, data_list):
        self.put(a, b, self.out_ann, [ann, data_list])
 
    # for other decoders
    def put_bin(self, data):
        self.put(self.ss_block, self.es_block, self.out_binary, data)

 

    # ==============================
    # Measure duty cycle of one bit
    # ==============================
    def get_duty_cycle(self):
        '''read 1 bit from target line'''
        # self.samplenum = current index, 由la提供
        start_samplenum = self.samplenum # current edge

        # key: multi-detection usually encounter some besetting problems
        if self.hp_mode is True:
            self.wait({1: 'f'}) 
            end_samplenum = self.samplenum
            self.wait({1: 'r'}) 
        else:
            self.wait({0: 'f'}) 
            end_samplenum = self.samplenum
            self.wait({0: 'r'})    
             
        self.ss_block = start_samplenum
        self.es_block = self.samplenum 

        # Calculate the period, the duty cycle, and its ratio.
        period = self.es_block - self.ss_block
        if period == 0:
            return 0  # NO PULSE
        duty = end_samplenum - start_samplenum 

        # Report the duty cycle in percent.
        percent = float((duty / period) * 100)  
        return percent
    
    # ==============================
    # Decode bit via duty cycle
    # ============================== 
    def get_bit(self):
        duty_cycle = self.get_duty_cycle() 
        bit = (duty_cycle >= self.threshold) ^ self.bit_def
        self.put_ann(self.ss_block, self.es_block, 7, [f"{duty_cycle:.1f}%"])
        return int(bit)
    
    # ==============================
    # For HP, different waveform/logic in response
    # Decode bit via reference
    # ==============================
    def get_response_bit(self):
        self.ss_block = self.samplenum
 
        self.wait([{0:'r', 1: 'h'}, {0:'l', 1: 'f'}])   
        if (self.matched & (0b1 << 0)):   # is uint64 integer
            bit = 1  
        elif (self.matched & (0b1 << 1)):
            bit = 0 
        else:
            raise ValueError('idk')
         
        self.wait({1: 'r'})  # to next pulse
        self.es_block = self.samplenum 
        
        return int(bit)
        

    # gerneral get bits func
    def get_bits(self, n):  
        func = self.get_bit if self.is_response_flag is False else self.get_response_bit

        val = 0   
        for _ in range(n):
            val = (val<<1) | func()   # call at here

        return int(val)
    
 
    def get_data_len(self):
       '''1 byte of data len, also write into self.data_len'''
       self.ss_byte = self.samplenum  
       self.data_len =  self.get_bits(8)    
       self.es_byte = self.samplenum
       return str(self.data_len)
    
    
    def get_byte(self):
        self.ss_byte = self.samplenum
        val = self.get_bits(8) 
        self.es_byte = self.samplenum
        return val
 

    def write_databytes(self, byte_size):
        self.databytes = []
        self.ss_byte = self.samplenum
        val = self.get_bits(8 * byte_size)
        self.es_byte = self.samplenum
        self.databytes.append(f"0x{val:0{2 * byte_size}x}")  # 左側補0x00至指定長
 

    def is_stop(self): 
        '''defined by raw signal's low duration''' 
        self.ss_byte = self.samplenum
        self.wait({1: 'f'})
        self.ss_block = self.samplenum
        try:
            self.wait({1: 'r'})
            self.es_block = self.samplenum  
        except:
            self.es_block = self.samplenum  
        samples = self.es_block - self.ss_block
        return samples > (self.samplerate * 150e-6)   # set 0.15 mini-sec halt as stop 
 


    # 解码函数，解码任务开始时由c底层代码调用
    # 这里不断循环等待所有采样数据被处理完成 
    # 软件会自动根据annotation_rows的设置，决定显示在哪一行
    # self.wait()可带参数: 符合的下個idx；不带参数:返回每个channel采样数据
    # 参数{0:'r'}， 0表示匹配channels idx = 0，'r'表示查找向上边沿
    # wait函数可传多个条件，与 AND:{0:'f',１:'r'},　或 OR：[{0:'f'},{１:'r'}]
    # h:高电平，l:低电平，r:向上边沿，f:向下边沿，e:向上沿或向下沿, n:高or低电平
    # wait函数前的变量(a,b)，对应的数量由定义的channels里的通道数决定，包括可选通道
    # optional_channels 。例如：channels和optional_channels共定义了４个通道，
    # 则变成(a,b,c,d) = self.wait()，共四个变量

    # 底层模块提供的属性：
    # 1. self.samplenum 当前wait()调用匹配结束的采样点位置
    # 2. self.matched 本次调用wait()后所有通道的匹配结果信息，是一个uint64类型数值，
    # 表示０到63个通道的匹配信息，通过位运算来获取具体信息。
    def decode(self):

        mode = self.options['mode']   
        
        self.wait({0: 'f' if self.options['polarity'] == 'active-low' else 'r'})
  
        if mode == 'none':
            while True:
                bit = self.get_bit()
                self.put_ann(self.ss_block, self.es_block, 3, [str(bit)])

        elif mode == 'HP':  
            _, optional = self.wait() 
            
            if optional is None:
                raise  ChannelError('HP mode require optional channel.')

            while True: 
                if self.state == 'FIND START':
                    if self.get_bit() == 1:
                        self.state = 'GET CMD'
                        self.put_ann(self.ss_block, self.es_block, 0 ,['Start'])  # annotations idx = 0


                elif self.state == 'GET CMD':  
                    self.cmd = self.get_byte()
                    self.put_ann(self.ss_byte, self.es_byte, 1 ,[hex(self.cmd)]) 
                    self.state = 'GET DATA LEN'                        


                elif self.state == 'GET DATA LEN': 
                    str_data_len = self.get_data_len() 
                    self.put_ann(self.ss_byte, self.es_byte, 2 ,[str_data_len])  

                    self.get_byte()   # next byte is len ^ 0xff, useless 

                    if self.data_len == 0:
                        self.state = 'WAIT'
                        self.is_response_flag = bool(self.cmd == 0x1a) 
                        self.put_ann(self.ss_byte, self.es_byte, 3 ,['None'])   # empty data  
                        self.put_ann(self.ss_byte, self.es_byte, 4 ,['None'])   # empty crc
                    else:
                        self.state = 'GET DATA'  


                elif self.state == 'GET DATA':
                    size = self.data_len  # reserved 
                    for _ in range(self.data_len // size): 
                        self.write_databytes(size)
                        self.put_ann(self.ss_byte, self.es_byte, 3, self.databytes)  # annotations idx = 3 
                    self.state = 'GET CRC'


                elif self.state == 'GET CRC':
                    crc_val = self.get_byte()
                    self.put_ann(self.ss_byte, self.es_byte, 4, [hex(crc_val)])
                    self.state = 'WAIT' 
                    self.is_response_flag = False   # either read or send data exist in 1 round, ignore 0x20 while sending data


                elif self.state == 'WAIT':  

                    if self.is_response_flag: 
                        # read response
                        val = self.get_byte()   

                        if val == 0x20:
                            self.put_ann(self.ss_byte, self.es_byte, 1 ,[hex(val)])  # is response cmd
                            self.state = 'GET DATA LEN' 
                        elif val == 0x3f:
                            self.put_ann(self.ss_byte, self.es_byte, 1 ,['Charging'])
                            self.put_ann(self.ss_byte, self.es_byte, 2 ,['None'])   # empty len  
                            self.put_ann(self.ss_byte, self.es_byte, 3 ,['None'])   # empty data  
                            self.put_ann(self.ss_byte, self.es_byte, 4 ,['None'])   # empty crc
                            self.is_response_flag = False
                        # for debug only
                        #elif val ==  0xff or val == 0x00:
                        #    self.put_ann(self.ss_byte, self.es_byte, 1 ,[hex(val)])
                        #else:
                        #    self.put_ann(self.ss_byte, self.es_byte, 1 ,[hex(val)])
                        #    #raise ValueError(f'unknown cmd: {hex(val)}')
 
                    elif self.is_stop():
                        self.state = 'FIND START' 
                        self.put_ann(self.ss_byte, self.es_block, 6, ['Stop']) 

        else:
            raise ModeError('not supported mode')

 