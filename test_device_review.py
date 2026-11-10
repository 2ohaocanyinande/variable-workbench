import tempfile
import unittest
from pathlib import Path

import device_review
import workbench as w


class DeviceReviewTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=w.BASE)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root/'board.ioc').write_text('Mcu.Name=STM32F103C8Tx\n')
        (self.root/'imu.h').write_text(
            '#define LSM6DSR_ADDR 1\n#define QMC5883L_OUT_X 2\n#define QMC5883L_STATUS_DATA_READY 3\n')
        self.driver = self.root/'imu.c'
        self.driver.write_text('''#include "imu.h"
void IMU963RA_GetAccel(void) {
    HAL_I2C_Mem_Read(&bus, LSM6DSR_ADDR, AX, 1, &data, 1, 10);
}
''')
        self.main = self.root/'main.c'
        self.main.write_text('''int main(void) {
    IMU963RA_GetAccel();
}
''')

    def scan(self):
        scan = w.scan_project(self.root)
        endpoint = next(e for e in scan['inventory']['endpoints'] if e['channel']=='LSM6DSR_ADDR')
        data = dict(scope='interface', id=endpoint['id'], root=scan['root'],
                    project_hash=scan['project_hash'])
        return scan, data

    def test_renamed_wrapper_resolves_typed_register_and_call_site(self):
        self.driver.write_text('''TIM_TypeDef *units[] = {TIM2};
void random_name(int value, int route, int block) {
    if (route == 1) units[block]->CCR1 = value;
    if (route == 2) units[block]->CCR2 = value;
}
void pwm_init(int device, int route, int unused) {}
''')
        self.main.write_text('''int main(void) {
    random_name(23, TIM2_CH2, TIM_2);
    pwm_init(TIM_2, TIM2_CH3, 50);
    // random_name(42, TIM2_CH1, TIM_2);
}
''')
        endpoints = w.scan_project(self.root)['inventory']['endpoints']
        self.assertEqual([(e['family'], e['handle'], e['channel']) for e in endpoints],
                         [('PWM', 'TIM_2', 'TIM2_CH2')])
        self.assertEqual(endpoints[0]['calls'][0]['line'], 2)
        self.assertEqual(endpoints[0]['register_evidence'][0]['path'], 'imu.c')
        self.assertEqual(endpoints[0]['register_evidence'][0]['line'], 4)

    def test_magnetometer_definitions_status_read_and_application_path(self):
        scan, data = self.scan()
        result = device_review.review(scan,data)
        mag = next(c for c in result['components'] if c['name']=='QMC5883L')
        self.assertTrue(mag['definitions'])
        self.assertFalse(mag['sampling'])
        accel = next(c for c in result['components'] if '加速度' in c['name'])
        self.assertTrue(accel['sampling'][0]['from_main'])
        self.driver.write_text(self.driver.read_text()+'''void IMU963RA_GetMag(void) {
    HAL_I2C_Mem_Read(&bus, QMC5883L_ADDR, QMC5883L_STATUS_DATA_READY, 1, &data, 1, 10);
}
''')
        with self.assertRaisesRegex(ValueError,'重新扫描'):
            device_review.review(scan,data)
        scan, data = self.scan()
        mag = next(c for c in device_review.review(scan,data)['components'] if c['name']=='QMC5883L')
        self.assertIsNone(mag['sampling'][0]['operation'])
        self.driver.write_text(self.driver.read_text().replace('QMC5883L_STATUS_DATA_READY','QMC5883L_OUT_X'))
        scan, data = self.scan()
        mag = next(c for c in device_review.review(scan,data)['components'] if c['name']=='QMC5883L')
        self.assertFalse(mag['sampling'][0]['from_main'])
        self.main.write_text(self.main.read_text().replace('    IMU963RA_GetAccel();','    IMU963RA_GetMag();'))
        scan, data = self.scan()
        mag = next(c for c in device_review.review(scan,data)['components'] if c['name']=='QMC5883L')
        self.assertTrue(mag['sampling'][0]['from_main'])
        self.assertEqual(mag['sampling'][0]['operation']['path'],'imu.c')

    def test_numeric_review_requires_matching_device_and_value(self):
        self.main.write_text('''int main(void) {
    huart1.Init.BaudRate = 115200;
    HAL_UART_Init(&huart1);
    huart2.Init.BaudRate = 9600;
    HAL_UART_Init(&huart2);
    HAL_UART_Transmit(&huart1, data, size, timeout);
    HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_1);
}
''')
        scan=w.scan_project(self.root)
        uart=next(e for e in scan['inventory']['endpoints'] if e['family']=='UART')
        pwm=next(e for e in scan['inventory']['endpoints'] if e['family']=='PWM')
        scan['device_report']={'devices':[{'id':'device','name':'测试设备','endpoint_ids':[uart['id'],pwm['id']],
            'features':['波特率 115200','波特率 9600','PWM TIM_CHANNEL_1（占空比 50%）',
                        'PWM TIM_CHANNEL_2','读取转速（16位有符号，100 rpm）','读取距离（0.2～4 m）']}]}
        data=dict(scope='device',id='device',root=scan['root'],project_hash=scan['project_hash'])
        result=device_review.review(scan,data)
        claims=result['numeric_claims']
        self.assertEqual([c['status'] for c in claims],['verified','conflict','verified','pending','pending'])
        self.assertEqual(claims[0]['evidence'][0]['line'],2)
        self.assertIn('115200',claims[1]['reason'])
        self.assertIn('16位',claims[-1]['feature'])
        self.assertEqual(len(result['unit_claims']),3)
        self.assertFalse(device_review.requires_numeric_review({'features':['读取距离（0.2～4 m）']}))
        self.assertFalse(device_review.requires_numeric_review({'features':['读取转速（16位有符号，100 rpm）']}))
        self.assertFalse(device_review.requires_numeric_review({'features':['按行显示（Line1~Line4）','配置1停止位','ADC通道15']}))
        self.assertTrue(device_review.requires_numeric_review({'features':['设置占空比(-10000~10000)']}))

    def test_gpio_button_needs_level_transitions(self):
        self.main.write_text('''void read_inputs(void) {
    state.val = HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_1);
    other.val = HAL_GPIO_ReadPin(GPIOB, GPIO_PIN_2);
    if (state.val == 0 && state.last == 1) state.down = 1;
    if (state.val == 1 && state.last == 0) state.up = 1;
    state.last = state.val;
}
''')
        scan=w.scan_project(self.root)
        inputs={e['channel']:e.get('button_symbol') for e in scan['inventory']['endpoints'] if e['family']=='GPIO'}
        self.assertEqual(inputs,{'GPIO_PIN_1':'state','GPIO_PIN_2':None})

    def test_duty_range_requires_instance_clamp_and_uart_payload(self):
        self.driver.write_text('''#include "limits.h"
static int16_t clamp(int16_t value) {
    if (value > MAX_DUTY) { return MAX_DUTY; }
    if (value < MIN_DUTY) { return MIN_DUTY; }
    return value;
}
static int emit(int16_t value) {
    uint8_t frame[2];
    uint16_t raw = (uint16_t)value;
    frame[0] = (uint8_t)((raw >> 8) & 0xFF);
    frame[1] = (uint8_t)(raw & 0xFF);
    return HAL_UART_Transmit(&uart, frame, 2, 10);
}
static int flush(void) {
    return emit(motors[LEFT].duty);
}
int set_value(int motor, int16_t value) {
    motors[motor].duty = clamp(value);
    return flush();
}
''')
        (self.root/'limits.h').write_text('#define MIN_DUTY -10000\n#define MAX_DUTY 10000\n')
        self.main.write_text('int main(void) { set_value(LEFT, 500); set_value(RIGHT, 500); }\n')

        def review(instance):
            scan=w.scan_project(self.root)
            endpoint=next(e for e in scan['inventory']['endpoints'] if e['family']=='UART')
            scan['device_report']={'devices':[{'id':'motor','name':'电机','instance':instance,
                'endpoint_ids':[endpoint['id']],'features':['设置占空比(-10000~10000)','设置占空比(-9000~9000)']}]}
            data=dict(scope='device',id='motor',root=scan['root'],project_hash=scan['project_hash'])
            return [c['status'] for c in device_review.review(scan,data)['numeric_claims']]

        self.assertEqual(review('LEFT'),['verified','conflict'])
        self.assertEqual(review('RIGHT'),['pending','pending'])
        self.driver.write_text(self.driver.read_text().replace('(uint8_t)(raw & 0xFF)','0'))
        self.assertEqual(review('LEFT'),['pending','pending'])

    def test_servo_range_requires_the_selected_compare_channel(self):
        self.driver.write_text('''#include "limits.h"
void start(void) {
    HAL_TIM_PWM_Start(&timer, TIM_CHANNEL_1);
    HAL_TIM_PWM_Start(&timer, TIM_CHANNEL_2);
}
void write_pulse(int servo, unsigned count) {
    if (count > HIGH) count = HIGH;
    if (count < LOW) count = LOW;
    switch (servo) {
    case SERVO_1: TIM3->CCR1 = count; break;
    case SERVO_2: TIM3->CCR2 = count; break;
    }
}
''')
        (self.root/'limits.h').write_text('#define LOW 500\n#define HIGH 2500\n')
        self.main.write_text('''void init(void) {
    timer.Instance = TIM3;
    HAL_TIM_PWM_Init(&timer);
}
''')
        scan=w.scan_project(self.root)
        endpoint=next(e for e in scan['inventory']['endpoints'] if e['channel']=='TIM_CHANNEL_2')
        motor={'id':'servo','name':'舵机','instance':'SERVO_2','endpoint_ids':[endpoint['id']],
               'features':['设置PWM脉宽（500~2500us）','设置PWM脉宽（400~2600计数）']}
        scan['device_report']={'devices':[motor]}
        data=dict(scope='device',id='servo',root=scan['root'],project_hash=scan['project_hash'])
        result=device_review.review(scan,data)
        self.assertEqual([c['status'] for c in result['numeric_claims']],['verified','conflict'])
        self.assertIn('预分频',result['unit_claims'][0]['reason'])
        motor['instance']='SERVO_1'
        self.assertEqual(device_review.review(scan,data)['numeric_claims'][0]['status'],'pending')
