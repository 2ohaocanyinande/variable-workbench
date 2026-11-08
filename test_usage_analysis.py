import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import usage_analysis as usage
import workbench as w


SOURCE = '''#include "driver/ledc.h"
void zz(uint32_t x) {
    ledc_set_duty(0, 1, x);
}
void yy(uint32_t y) {
    zz(y);
}
void run(void) {
    uint32_t abc = 17;
    uint32_t motor_speed = 3;
    yy(abc);
    printf("%d", motor_speed);
}
'''


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=w.BASE)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        isolated_state = self.root/'state'
        isolated_state.mkdir()
        state_patch = patch.object(w, 'STATE', isolated_state)
        state_patch.start()
        self.addCleanup(state_patch.stop)
        (self.root/'CMakeLists.txt').write_text('idf_component_register(SRCS "a.c")')
        self.source = self.root/'a.c'
        self.source.write_text(SOURCE)
        self.scan = w.scan_project(self.root)

    def packet(self):
        return usage.make_packet(self.scan, '解释输出变量用途')

    def answer(self, packet):
        c = next(c for c in packet['candidates'] if c['symbol'] == 'abc')
        sid = next(s for s in c['evidence_ids'] if 'yy(abc)' in packet['snippets'][s]['code'])
        return {'findings': [{'candidate_id': c['id'], 'purpose': '可能参与 PWM 输出',
                             'reason': 'abc 作为实参经 yy、zz 传入 PWM 设置函数；硬件用途待确认。',
                             'evidence': [{'snippet_id': sid, 'quote': 'yy(abc);'}],
                             'selectable': True, 'access': 'rw'}]}

    def test_arbitrary_names_and_wrapper_chain(self):
        c = next(c for c in self.scan['usage']['candidates'] if c['symbol'] == 'abc')
        self.assertIn(['run', 'yy', 'zz', 'ledc_set_duty'], c['call_chains'])
        # Renaming user symbols doesn't alter the peripheral evidence.
        self.source.write_text(SOURCE.replace('abc', 'unrelated_name').replace('zz', 'other').replace('yy', 'wrap'))
        renamed = w.scan_project(self.root)
        c2 = next(c for c in renamed['usage']['candidates'] if c['symbol'] == 'unrelated_name')
        self.assertEqual(c['clues'], c2['clues'])
        self.assertEqual(c2['scope'], 'run')

    def test_quotes_and_no_write_authority(self):
        p = self.packet()
        answer = self.answer(p)
        findings = usage.validate_findings(answer, p)
        self.assertFalse(findings[0]['selectable'])
        with self.assertRaises(ValueError): w.generate(self.scan, [findings[0]['candidate']['id']])
        answer['findings'][0]['evidence'][0]['quote'] = 'totally_fabricated_code();'
        with self.assertRaises(ValueError): usage.validate_findings(answer, p)
        answer['findings'][0]['candidate_id'] = 'unknown'
        with self.assertRaises(ValueError): usage.validate_findings(answer, p)

    def test_preview_offline_and_input_budget(self):
        with patch.object(w, 'SCAN', self.scan), patch.object(w, 'API', {}), patch.object(w.urllib.request, 'urlopen', side_effect=AssertionError('network')):
            result = w.analyze_usage({'preview': True})
            self.assertLess(result['bytes'], 49000)
            with self.assertRaises(ValueError): w.analyze_usage({})

    def test_targeted_question_and_sanitized_errors(self):
        packet = usage.make_packet(self.scan, '解释 abc 的作用')
        self.assertEqual([c['symbol'] for c in packet['candidates']], ['abc'])
        for status in (400, 401, 402, 429, 503):
            error = urllib.error.HTTPError('https://example.invalid', status, 'SECRET_KEY', None, None)
            message = w.model_error(error)
            self.assertIn(str(status), message)
            self.assertNotIn('SECRET_KEY', message)
        self.assertIn('联网权限', w.model_error(urllib.error.URLError(PermissionError())))
        self.assertIn('超时', w.model_error(TimeoutError()))

    def test_network_calls_callbacks_and_literal_redaction(self):
        self.source.write_text('''#include "lwip/sockets.h"
void strange(void *opaque, esp_event_base_t b, int32_t e, void *d) {
    bool xyz = e == IP_EVENT_STA_GOT_IP;
    printf("secret-in-comment-or-log", xyz);
}
void setup(void) {
    wifi_config_t q = {.sta = {.ssid = "PRIVATE_SSID", .password = "PRIVATE_PASSWORD"}};
    esp_wifi_set_config(WIFI_IF_STA, &q);
    esp_event_handler_instance_register(IP_EVENT, ESP_EVENT_ANY_ID, strange, NULL, NULL);
    esp_wifi_connect();
}
void wire(void) {
    int a = socket(AF_INET, SOCK_DGRAM, 0);
    char z[64];
    recvfrom(a, z, sizeof(z), 0, NULL, NULL);
    // PRIVATE_COMMENT
    esp_mqtt_client_publish(NULL, "PRIVATE_TOPIC", z, 4, 0, 0);
}
void radio(void) {
    esp_ble_gap_start_scanning(3);
}
''')
        scan = w.scan_project(self.root)
        packet = usage.make_packet(scan, '分析网络连接和收发', 'network')
        self.assertTrue(packet['candidates'])
        roles = {r for c in packet['candidates'] for r in c['clues']}
        for role in ('Wi-Fi 配置', 'Wi-Fi 连接', 'Wi-Fi/IP 状态事件注册', 'MQTT 发布', 'BLE 扫描', 'TCP/UDP：套接字接收及来源地址'):
            self.assertIn(role, roles)
        callback = next(c for c in packet['candidates'] if c['symbol'] == 'xyz')
        self.assertIn('Wi-Fi/IP 状态事件注册', callback['clues'])
        text = json.dumps(packet)
        for secret in ('PRIVATE_SSID', 'PRIVATE_PASSWORD', 'PRIVATE_TOPIC', 'PRIVATE_COMMENT', 'secret-in-comment-or-log'):
            self.assertNotIn(secret, text)
        self.assertIn('SOCK_DGRAM', text)

    def test_network_not_guessed_from_variable_name_or_custom_send(self):
        self.source.write_text('''void send(int a) { int wifi_speed = a; }
void task(void) { int mqtt_status = 0; send(mqtt_status); }
''')
        scan = w.scan_project(self.root)
        self.assertEqual(usage.make_packet(scan, '联网功能', 'network')['candidates'], [])

    def test_stm32_cubemx_and_hal_wrappers(self):
        (self.root/'CMakeLists.txt').unlink()
        (self.root/'board.ioc').write_text('Mcu.Name=STM32F407VGTx\n')
        self.source.write_text('''TIM_HandleTypeDef htim;
void write_output(uint32_t p) {
    __HAL_TIM_SET_COMPARE(&htim, TIM_CHANNEL_2, p);
}
void app(void) {
    uint32_t anything = 13;
    write_output(anything);
    uint32_t q = HAL_ADC_GetValue(&hadc);
    HAL_UART_Transmit_DMA(&huart, buffer, q);
}
''')
        scan = w.scan_project(self.root)
        self.assertEqual(scan['platform'], 'stm32')
        packet = usage.make_packet(scan, '分析外设', 'stm32')
        candidate = next(c for c in packet['candidates'] if c['symbol'] == 'anything')
        self.assertIn(['app', 'write_output', '__HAL_TIM_SET_COMPARE'], candidate['call_chains'])
        with self.assertRaisesRegex(ValueError, '尚未适配'): w.generate(scan, ['anything'])

    def test_keil_marker_sources_and_vendor_omission(self):
        (self.root/'CMakeLists.txt').unlink()
        (self.root/'Project.uvprojx').write_text('''<Project><Targets><Target><TargetName>T</TargetName><TargetOption><Device>STM32F103C8</Device></TargetOption><Groups><File><FilePath>a.c</FilePath></File></Groups></Target></Targets></Project>''')
        self.source.write_text('void f(uint16_t x) { TIM_SetCompare1(TIM2, x); }')
        vendor = self.root/'Drivers'/'STM32F4xx_HAL_Driver'
        vendor.mkdir(parents=True)
        (vendor/'large.h').write_text('x'*2_100_000)
        scan = w.scan_project(self.root)
        self.assertEqual(scan['platform'], 'stm32')
        self.assertEqual(scan['project_info']['vendor_files_omitted'], 1)
        self.assertTrue(scan['usage']['stm32'][0]['active'])
        from project_picker import browse
        self.assertTrue(browse(self.root, self.root)['is_project'])

    def test_cubeide_and_non_stm32_keil(self):
        (self.root/'CMakeLists.txt').unlink()
        (self.root/'.project').write_text('<projectDescription>com.st.stm32cube.ide.mcu.MCUProjectNature</projectDescription>')
        self.assertEqual(w.scan_project(self.root)['platform'], 'stm32')
        (self.root/'.project').unlink()
        (self.root/'other.uvprojx').write_text('<Project><Device>MSPM0G3507</Device></Project>')
        with self.assertRaises(ValueError): w.scan_project(self.root)

    def test_device_inventory_groups_channels_not_functions(self):
        self.source.write_text('''void init(void) {
 HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_1);
 HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_2);
 HAL_UART_Receive_DMA(&huart2, rx, 8);
}
void output(uint16_t a) {
 __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_1, a);
 HAL_UART_Transmit_DMA(&huart2, tx, 8);
}
''')
        scan = w.scan_project(self.root)
        endpoints = scan['inventory']['endpoints']
        self.assertEqual(len(endpoints), 3)  # 2 channels + 1 serial link, not 5 calls
        self.assertEqual(len([e for e in endpoints if e['family']=='PWM']), 2)
        self.assertTrue(all('待识别' in e['status'] for e in endpoints))

    def test_common_tof_driver_and_no_address_only_guess(self):
        self.source.write_text('''#define VL53L0X_ADDRESS 0x29
void arbitrary(void) { HAL_I2C_Mem_Read(&hbus, VL53L0X_ADDRESS, 0x14, 1, data, 12, 100); }
''')
        scan=w.scan_project(self.root)
        hint=scan['inventory']['endpoints'][0]['module_hints'][0]
        self.assertEqual(hint['model'],'VL53L0X')
        self.assertIn('激光测距',hint['category'])
        self.source.write_text('void arbitrary(void) { HAL_I2C_Mem_Read(&hbus, 0x29, 0, 1, data, 12, 100); }')
        self.assertEqual(w.scan_project(self.root)['inventory']['endpoints'][0]['module_hints'],[])

    def test_common_driver_api_without_direct_hal_and_bsp_kept(self):
        (self.root/'CMakeLists.txt').unlink()
        (self.root/'board.ioc').write_text('Mcu.Name=STM32F407VGTx\n')
        component=self.root/'Drivers'/'BSP'/'Components'
        component.mkdir(parents=True)
        (component/'range.c').write_text('void go(void) { VL53L1X_GetDistance(&target, &distance); }')
        scan=w.scan_project(self.root)
        self.assertIn('Drivers/BSP/Components/range.c',scan['files'])
        self.assertTrue(any(e['module_hints'][0]['model']=='VL53L1X' for e in scan['inventory']['endpoints']))

    def test_generic_bus_wrapper_keeps_sensor_call_context(self):
        self.source.write_text('void transport(uint8_t reg, uint8_t *data) { HAL_I2C_Mem_Read(&h, 0x68, reg, 1, data, 6, 100); }')
        (self.root/'sensor.c').write_text('''void sample(void) {
 uint8_t data[6];
 transport(0x43, data);
 int16_t angular_rate = (data[0] << 8) | data[1];
}
''')
        scan=w.scan_project(self.root)
        from device_inventory import packet
        text=json.dumps(packet(scan))
        self.assertIn('angular_rate',text)
        self.assertIn('sensor.c',text)

    def test_ism_interface_is_tentative_not_exact_model(self):
        self.source.write_text('''void setup(void) {
 HAL_GPIO_WritePin(ISM_CS_GPIO_Port, ISM_CS_Pin, GPIO_PIN_SET);
 config.Pin = ISM_INT_Pin;
}
''')
        e=w.scan_project(self.root)['inventory']['endpoints'][0]
        hint=e['module_hints'][0]
        self.assertIn('疑似 IMU',hint['category'])
        self.assertEqual(hint['model'],'型号待确认')
        self.assertEqual(hint['strength'],'tentative_interface')

    def test_generic_nine_byte_distance_protocol_not_specific_model(self):
        self.source.write_text('''void receive(void) {
 HAL_UART_Receive_DMA(&link, b, 9);
 if (b[0] != 0x59 || b[1] != 0x59) return;
 uint16_t x = b[2] | (b[3] << 8);
}
''')
        hint=w.scan_project(self.root)['inventory']['endpoints'][0]['module_hints'][0]
        self.assertIn('激光测距',hint['category'])
        self.assertIn('具体型号待确认',hint['model'])

    def test_catalog_tokens_in_comment_or_log_not_identification(self):
        self.source.write_text('''void go(void) {
 // VL53L0X is a TODO
 printf("BMI270");
 HAL_GPIO_WritePin(GPIOB, GPIO_PIN_1, 1);
}
''')
        self.assertEqual(w.scan_project(self.root)['inventory']['endpoints'][0]['module_hints'],[])

    def test_device_instance_evidence_and_no_control_authority(self):
        from device_inventory import packet, validate
        self.source.write_text('''void output(uint16_t a) {
 __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_1, a);
}
''')
        scan=w.scan_project(self.root);p=packet(scan);endpoint=p['endpoints'][0];sid=endpoint['evidence_ids'][0]
        answer={'devices':[{'name':'待确认输出设备','kind':'unknown','instance':'TIM_CHANNEL_1',
                            'endpoint_ids':[endpoint['id']], 'features':['调整输出比较值'], 'reason':'仅由比较值设置确认通道，无法确认物理设备。',
                            'evidence':[{'snippet_id':sid,'quote':'__HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_1, a);'}],
                            'writable':True}]}
        result=validate(answer,p)
        self.assertFalse(result[0]['writable'])
        settings={'enabled':True,'url':'http://127.0.0.1:1/v1','model':'fixture','key':''}
        response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer)}}]}
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return json.dumps(response).encode()
        with patch.object(w,'SCAN',scan),patch.object(w,'API',settings),patch.object(w.urllib.request,'urlopen',return_value=Response()):
            report=w.analyze_usage({'mode':'devices'})
            self.assertEqual(len(report['devices']),1)
            self.assertEqual(report['findings'],[])
            self.assertIn('device_report',scan)
        answer['devices'][0]['instance']='INVENTED_CHANNEL'
        with self.assertRaises(ValueError): validate(answer,p)
        answer['devices'][0]['endpoint_ids']=['unknown-endpoint']
        with self.assertRaises(ValueError): validate(answer,p)

    def test_multiline_quote_ignores_line_labels_not_code_changes(self):
        from code_evidence import quote_exists
        source='61: case OUT_1:\n62:     set_value(&timer, CH_1, value);\n63:     break;'
        self.assertTrue(quote_exists('case OUT_1:\nset_value(&timer, CH_1, value);',source))
        self.assertFalse(quote_exists('case OUT_1:\nset_value(&timer, CH_2, value);',source))
        self.assertFalse(quote_exists('uint16_tx = 1;', '12: uint16_t x = 1;'))
        self.assertFalse(quote_exists('a > > b;', '10: a >> b;'))

    def test_partial_validation_keeps_valid_device(self):
        from device_inventory import packet, validate_partial
        self.source.write_text('void f(uint16_t value) { __HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_1, value); }')
        scan=w.scan_project(self.root);p=packet(scan);endpoint=p['endpoints'][0];sid=endpoint['evidence_ids'][0]
        valid={'name':'输出1','kind':'unknown','instance':'TIM_CHANNEL_1','endpoint_ids':[endpoint['id']],
               'reason':'仅能确认比较值设置。','features':[],
               'evidence':[{'snippet_id':sid,'quote':'__HAL_TIM_SET_COMPARE(&htim3, TIM_CHANNEL_1, value);'}]}
        bad=json.loads(json.dumps(valid));bad['name']='错误引用';bad['evidence'][0]['quote']='fake_call(TIM_CHANNEL_1);'
        devices,warnings=validate_partial({'devices':[valid,bad]},p)
        self.assertEqual(len(devices),1)
        self.assertEqual(len(warnings),1)
        self.assertEqual(warnings[0]['index'],2)
        self.assertFalse(devices[0]['writable'])

    def test_partial_device_citations_keep_verified_instance_without_features(self):
        from device_inventory import packet,validate_partial
        self.source.write_text('void f(float value) { __HAL_TIM_SET_COMPARE(&timer, TIM_CHANNEL_1, value); }')
        p=packet(w.scan_project(self.root));e=p['endpoints'][0];sid=e['evidence_ids'][0]
        item={'name':'输出','kind':'unknown','instance':'TIM_CHANNEL_1','endpoint_ids':[e['id']],
              'features':['未经验证的额外功能'],'reason':'测试部分引文失败。','evidence':[
                  {'snippet_id':sid,'quote':'__HAL_TIM_SET_COMPARE(&timer, TIM_CHANNEL_1, value);'},
                  {'snippet_id':sid,'quote':'fake_call();'}]}
        good,bad=validate_partial({'devices':[item]},p)
        self.assertFalse(bad);self.assertTrue(good[0]['evidence_partial'])
        self.assertFalse(good[0]['writable']);self.assertNotIn('未经验证的额外功能',good[0]['features'])
        item['instance']='invented'
        self.assertFalse(validate_partial({'devices':[item]},p)[0])

    def test_startup_never_opens_saved_test_project(self):
        private=self.root/'untouched_test_case';private.mkdir()
        (private/'CMakeLists.txt').write_text('project(private)')
        (w.STATE/'project-session.json').write_text(json.dumps({'root':str(private)}))
        with patch.object(w,'SCAN'),patch.object(w,'PROJECT'),patch.object(w,'MANIFEST'),patch.object(w,'scan_project',wraps=w.scan_project) as scanner:
            w.initialize()
            self.assertEqual([call.args[0] for call in scanner.call_args_list],[w.BASE/'sample_esp32'])

    def test_nested_cube_project_is_not_mixed_with_parent(self):
        child=self.root/'copied_project';child.mkdir()
        (child/'other.ioc').write_text('Mcu.Name=STM32F407VGTx\n')
        (child/'other.c').write_text('void unrelated(void) { HAL_TIM_PWM_Start(&other, TIM_CHANNEL_1); }')
        scan=w.scan_project(self.root)
        self.assertNotIn('copied_project/other.c',scan['files'])
        self.assertIn('copied_project',scan['project_info']['nested_projects_omitted'])

    def test_wire_snippets_keep_paths_but_remove_line_label_overhead(self):
        self.source.write_text('void f(void) { HAL_TIM_PWM_Start(&h, TIM_CHANNEL_1); }')
        from device_inventory import packet
        p=packet(w.scan_project(self.root));sid=p['endpoints'][0]['evidence_ids'][0]
        self.assertTrue(sid.startswith('s_'))
        self.assertEqual(p['snippets'][sid]['path'],'a.c')
        self.assertTrue(p['snippets'][sid]['code'].startswith('void f'))

    def test_encoders_discovered_and_counter_reads_grouped(self):
        self.source.write_text('''void init(void) {
 HAL_TIM_Encoder_Start(&timerA, TIM_CHANNEL_ALL);
 HAL_TIM_Encoder_Start_IT(&timerB, TIM_CHANNEL_ALL);
}
void read(void) {
 uint16_t value = __HAL_TIM_GET_COUNTER(&timerA);
}
''')
        scan=w.scan_project(self.root)
        encoders=[e for e in scan['inventory']['endpoints'] if e['family']=='ENCODER']
        self.assertEqual({e['handle'] for e in encoders},{'timerA','timerB'})
        self.assertTrue(any(c['api']=='__HAL_TIM_GET_COUNTER' for c in encoders[0]['calls']))
        self.assertTrue(all(e['id'].startswith('ep_') and not any(c.isspace() for c in e['id']) for e in encoders))

    def test_oled_budget_not_consumed_by_font_table(self):
        (self.root/'text_font.h').write_text('const unsigned char font[] = {\n'+('0x00, '*60+'\n')*180+'};')
        self.source.write_text('''void motor(void) { HAL_TIM_PWM_Start(&h, TIM_CHANNEL_1); }
''')
        (self.root/'display.c').write_text('''#include "text_font.h"
void serial_clock(uint8_t x) { HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8, x); }
void serial_data(uint8_t x) { HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, x); }
void OLED_WriteByte(uint8_t value) { for(int i=0;i<8;i++) { serial_data(value&0x80); serial_clock(1); serial_clock(0); value<<=1; } }
''')
        scan=w.scan_project(self.root)
        from device_inventory import packet
        p=packet(scan)
        self.assertEqual(p['coverage']['sent'],p['coverage']['indexed'])
        self.assertGreater(p['coverage']['data_tables_omitted'],0)
        self.assertTrue(any(s['path']=='display.c' for s in p['snippets'].values()))
        self.assertFalse(any(s['path']=='text_font.h' for s in p['snippets'].values()))

    def test_gpio_composite_name_requires_same_port_pin_call(self):
        self.source.write_text('void set(void) { HAL_GPIO_WritePin(GPIOA, GPIO_PIN_2, 0); }')
        scan=w.scan_project(self.root)
        from device_inventory import packet,validate
        p=packet(scan);e=p['endpoints'][0];sid=e['evidence_ids'][0]
        item={'name':'未知输出','kind':'unknown','instance':'GPIOA_PIN_2','endpoint_ids':[e['id']],
              'features':[],'reason':'按同一调用组合端口与引脚。',
              'evidence':[{'snippet_id':sid,'quote':'HAL_GPIO_WritePin(GPIOA, GPIO_PIN_2, 0);'}]}
        self.assertIn('组合',validate({'devices':[item]},p)[0]['instance_binding'])
        item['instance']='GPIOB_PIN_2'
        with self.assertRaises(ValueError): validate({'devices':[item]},p)

    def test_main_includes_imu_must_not_classify_pwm_or_unrelated_gpio(self):
        (self.root/'MPU6050.h').write_text('void MPU6050_Read(void);')
        self.source.write_text('''#include "MPU6050.h"
void all(void) {
 MPU6050_Read();
 HAL_TIM_PWM_Start(&htim3, TIM_CHANNEL_3);
 HAL_GPIO_WritePin(ISM_CS_GPIO_Port, ISM_CS_Pin, 1);
 HAL_GPIO_WritePin(GPIOC, GPIO_PIN_9, 1);
 config.Pin = ISM_INT_Pin;
}
''')
        scan=w.scan_project(self.root)
        for e in scan['inventory']['endpoints']:
            if e['family']=='PWM' or e['handle']=='GPIOC': self.assertEqual(e['module_hints'],[])
        from common_modules import enrich
        ep=next(e for e in scan['inventory']['endpoints'] if e['family']=='PWM')
        ep['module_hints']=[{'model':'MPU6050','category':'IMU','strength':'driver_signature'}]
        result=enrich([{'endpoint_ids':[ep['id']],'kind':'servo','name':'舵机'}],[ep])
        self.assertNotIn('category',result[0])

    def test_sensor_module_conflict_has_consistent_name_and_features(self):
        from common_modules import enrich
        ep={'id':'ep_test','family':'MODULE','module_hints':[{'model':'MPU6050','category':'IMU',
            'driver_state':'存在读取调用','confidence':'驱动标识匹配','strength':'driver_signature'}]}
        d={'endpoint_ids':['ep_test'],'kind':'servo','name':'舵机1','features':['设置舵机角度'],'reason':'测试矛盾输入'}
        result=enrich([d],[ep])[0]
        self.assertIn('IMU',result['name'])
        self.assertNotIn('舵机',result['name'])
        self.assertNotIn('设置舵机角度',result['features'])
        self.assertEqual(result['original_ai_name'],'舵机1')

    def test_gpio_evidence_links_same_pins_not_other_ports(self):
        self.source.write_text('void init(void) { HAL_GPIO_WritePin(GPIOB, GPIO_PIN_8|GPIO_PIN_9, 0); }')
        (self.root/'display.c').write_text('void sda(int x) { HAL_GPIO_WritePin(GPIOB, GPIO_PIN_9, x); }')
        (self.root/'other.c').write_text('void other(int x) { HAL_GPIO_WritePin(GPIOC, GPIO_PIN_9, x); }')
        scan=w.scan_project(self.root)
        group=next(e for e in scan['inventory']['endpoints'] if e['path']=='a.c')
        proof=[scan['inventory']['snippets'][sid]['path'] for sid in group['evidence_ids']]
        self.assertIn('display.c',proof)
        self.assertNotIn('other.c',proof)

    def test_transitive_project_headers_belong_to_gpio_evidence(self):
        (self.root/'wiring.h').write_text('#define arbitrary_pin GPIO_PIN_2\n')
        (self.root/'gpio.h').write_text('#include "wiring.h"\n')
        self.source.write_text('#include "gpio.h"\nvoid init(void) { HAL_GPIO_WritePin(GPIOB, arbitrary_pin, 1); }')
        scan=w.scan_project(self.root)
        ep=scan['inventory']['endpoints'][0]
        self.assertIn('wiring.h',[scan['inventory']['snippets'][sid]['path'] for sid in ep['evidence_ids']])

    def test_instance_binding_uses_verified_call_without_substring_alias(self):
        self.source.write_text('''void init(void) { HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_1); }
void update(void) { TIM2->CCR1 = arbitrary_value; }
''')
        from device_inventory import packet,validate
        p=packet(w.scan_project(self.root));ep=p['endpoints'][0];sid=ep['evidence_ids'][0]
        item={'name':'PWM 输出','kind':'unknown','instance':'TIM_CHANNEL_1','endpoint_ids':[ep['id']],
              'features':[],'reason':'通道由初始化调用绑定，更新通过寄存器赋值。',
              'evidence':[{'snippet_id':sid,'quote':'TIM2->CCR1 = arbitrary_value;'}]}
        device=validate({'devices':[item]},p)[0]
        self.assertIn('补充绑定',device['instance_binding'])
        self.assertTrue(any('HAL_TIM_PWM_Start' in e['quote'] for e in device['evidence']))
        item['instance']='arbitrary'
        with self.assertRaises(ValueError): validate({'devices':[item]},p)

    def test_overlapping_quote_can_relocate_only_within_allowed_interface(self):
        self.source.write_text('''void init(void) { HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_1); }
''')
        (self.root/'other.c').write_text('void other(void) { HAL_GPIO_WritePin(GPIOC, GPIO_PIN_9, 1); }')
        from device_inventory import packet,validate
        p=packet(w.scan_project(self.root));ep=next(e for e in p['endpoints'] if e['family']=='PWM')
        other=next(e for e in p['endpoints'] if e['family']=='GPIO')
        item={'name':'PWM 输出','kind':'unknown','instance':'htim2','endpoint_ids':[ep['id']],
              'features':[],'reason':'引用编号错误，但代码本身属于这个接口。',
              'evidence':[{'snippet_id':other['evidence_ids'][0],'quote':'HAL_TIM_PWM_Start(&htim2, TIM_CHANNEL_1);'}]}
        self.assertTrue(validate({'devices':[item]},p)[0]['evidence'][0]['reference_corrected'])
        item['instance']='GPIO_PIN_9'
        item['evidence'][0]['quote']='HAL_GPIO_WritePin(GPIOC, GPIO_PIN_9, 1);'
        with self.assertRaises(ValueError): validate({'devices':[item]},p)

    def test_arbitrary_enum_array_instances_are_hints_not_devices(self):
        (self.root/'defs.h').write_text('typedef enum { arbitrary_a=0, arbitrary_b=1, unused=2 } item_id;')
        self.source.write_text('''#include "defs.h"
void send(void) { values[arbitrary_a]=1; values[arbitrary_b]=2; HAL_UART_Transmit(&serial, frame, 7, 10); }
''')
        from device_inventory import packet
        p=packet(w.scan_project(self.root))
        self.assertEqual(p['endpoints'][0]['instance_candidates'],['arbitrary_a','arbitrary_b'])
        self.assertNotIn('devices',p)

    def test_unknown_endpoint_recovers_only_from_complete_verified_call(self):
        self.source.write_text('void set(void) { HAL_GPIO_WritePin(GPIOC, GPIO_PIN_7, 1); }')
        from device_inventory import packet,validate_partial
        p=packet(w.scan_project(self.root));sid=p['endpoints'][0]['evidence_ids'][0]
        d={'name':'未知输出','kind':'unknown','instance':'GPIO_PIN_7','endpoint_ids':['ep_invented'],
           'features':[],'reason':'测试模型编号错误。',
           'evidence':[{'snippet_id':sid,'quote':'HAL_GPIO_WritePin(GPIOC, GPIO_PIN_7, 1);'}]}
        accepted,warnings=validate_partial({'devices':[d]},p)
        self.assertFalse(warnings)
        self.assertEqual(accepted[0]['endpoint_ids'],[p['endpoints'][0]['id']])
        self.assertTrue(accepted[0]['local_repairs'])
        d['evidence'][0]['quote']='HAL_GPIO_WritePin(GPIOB, GPIO_PIN_7, 1);'
        self.assertEqual(validate_partial({'devices':[d]},p)[0],[])

    def test_namespace_alias_and_gpio_macro_binding_remain_traceable(self):
        (self.root/'main.h').write_text('#define arbitrary_Pin GPIO_PIN_7\n#define arbitrary_GPIO_Port GPIOC\n')
        self.source.write_text('#include "main.h"\nvoid set(void) { HAL_GPIO_WritePin(GPIOC, GPIO_PIN_7, 1); }')
        from device_inventory import packet,validate_partial
        p=packet(w.scan_project(self.root));e=p['endpoints'][0];sid=e['evidence_ids'][0]
        d={'name':'未知输出','kind':'unknown','instance':'arbitrary_Pin','endpoint_ids':[e['id']],
           'features':[],'reason':'别名通过宏定义关联到同一端口与引脚。',
           'evidence':[{'snippet_id':sid,'quote':'HAL_GPIO_WritePin(GPIOC, GPIO_PIN_7, 1);'}]}
        good,bad=validate_partial({'devices':[d]},p)
        self.assertFalse(bad)
        self.assertTrue(any('#define arbitrary_Pin' in c['quote'] for c in good[0]['evidence']))
        (self.root/'main.h').write_text('#define arbitrary_Pin GPIO_PIN_7\n#define arbitrary_GPIO_Port GPIOB\n')
        p2=packet(w.scan_project(self.root))
        self.assertEqual(validate_partial({'devices':[d]},p2)[0],[])

    def test_short_pin_alias_becomes_exact_token_not_substring(self):
        self.source.write_text('void set(void) { HAL_GPIO_WritePin(x_Port, x_Pin, 1); }')
        from device_inventory import packet,validate_partial
        p=packet(w.scan_project(self.root));e=p['endpoints'][0];sid=e['evidence_ids'][0]
        d={'name':'未知输出','kind':'unknown','instance':'x','endpoint_ids':[e['id']],
           'features':[],'reason':'模型只返回简称，规范为已引用的精确引脚标识。',
           'evidence':[{'snippet_id':sid,'quote':'HAL_GPIO_WritePin(x_Port, x_Pin, 1);'}]}
        self.assertEqual(validate_partial({'devices':[d]},p)[0][0]['instance'],'x_Pin')

    def test_model_namespace_resolves_only_to_one_catalogue_driver_function(self):
        self.source.write_text('void read(void) { VL53L1_GetRangingMeasurementData(&device, &result); }')
        from device_inventory import packet,validate_partial
        p=packet(w.scan_project(self.root));e=p['endpoints'][0];sid=e['evidence_ids'][0]
        d={'name':'测距传感器','kind':'sensor','instance':'VL53L1','endpoint_ids':[e['id']],
           'features':[],'reason':'驱动前缀不能当作实际代码实例。',
           'evidence':[{'snippet_id':sid,'quote':'VL53L1_GetRangingMeasurementData(&device, &result);'}]}
        result=validate_partial({'devices':[d]},p)[0][0]
        self.assertEqual(result['instance'],'VL53L1_GetRangingMeasurementData')
        self.assertFalse(result['writable'])
        d['instance']='VL53'
        self.assertEqual(validate_partial({'devices':[d]},p)[0],[])

    def test_evidence_link_targets_actual_quote_line(self):
        from code_evidence import quote_source_line
        self.assertEqual(quote_source_line('set_value(&timer, CH_1, value);',
                         '61: case OUT_1:\n62:     set_value(&timer, CH_1, value);\n63: break;'),62)
        self.assertIsNone(quote_source_line('set_value(&timer, CH_2, value);',
                         '62: set_value(&timer, CH_1, value);'))

    def test_driver_namespace_normalizes_to_verified_function(self):
        self.source.write_text('''void OLED_WriteByte(int data) { HAL_GPIO_WritePin(GPIOC, GPIO_PIN_7, data); }
''')
        from device_inventory import packet,validate_partial
        p=packet(w.scan_project(self.root));e=p['endpoints'][0];sid=e['evidence_ids'][0]
        d={'name':'显示屏','kind':'display','instance':'OLED','endpoint_ids':[e['id']],
           'features':[],'reason':'规范化驱动命名空间，不把简称直接当源码变量。',
           'evidence':[{'snippet_id':sid,'quote':'void OLED_WriteByte(int data)'}]}
        result=validate_partial({'devices':[d]},p)[0][0]
        self.assertEqual(result['instance'],'OLED_WriteByte')
        self.assertTrue(result['local_repairs'])

    def test_omitted_common_module_is_visible_as_local_clue_not_instance(self):
        self.source.write_text('void read(void) { MPU6050_GetData(&a,&b,&c,&d,&e,&f); }')
        from device_inventory import packet,supplement_common_clues
        p=packet(w.scan_project(self.root))
        local=supplement_common_clues([],p)
        self.assertEqual(len(local),1)
        self.assertIn('实例待确认',local[0]['name'])
        self.assertEqual(local[0]['origin'],'local_clue')
        self.assertFalse(local[0]['writable'])
        self.assertEqual(supplement_common_clues([local[0]],p),[])

    def test_unrelated_gpio_is_not_a_supplemental_sensor(self):
        self.source.write_text('void set(void) { HAL_GPIO_WritePin(GPIOC, GPIO_PIN_7, 1); }')
        from device_inventory import packet,supplement_common_clues
        self.assertEqual(supplement_common_clues([],packet(w.scan_project(self.root))),[])

    def test_composite_timer_label_uses_call_not_handle_name(self):
        self.source.write_text('void init(void) { HAL_TIM_PWM_Start(&arbitrary, TIM_CHANNEL_3); }')
        from device_inventory import packet,validate_partial
        p=packet(w.scan_project(self.root));e=p['endpoints'][0];sid=e['evidence_ids'][0]
        d={'name':'输出','kind':'unknown','instance':'TIM3_CHANNEL_3','endpoint_ids':[e['id']],
           'features':[],'reason':'模型复合标签改用已验证通道，定时器别名未经确认。',
           'evidence':[{'snippet_id':sid,'quote':'HAL_TIM_PWM_Start(&arbitrary, TIM_CHANNEL_3);'}]}
        self.assertEqual(validate_partial({'devices':[d]},p)[0][0]['instance'],'TIM_CHANNEL_3')
        d['instance']='TIM3_CHANNEL_2'
        self.assertFalse(validate_partial({'devices':[d]},p)[0])

    def test_request_and_stale_source_rejection(self):
        p = self.packet()
        reply = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(self.answer(p))}}]}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return json.dumps(reply).encode()
        def respond(request, **kwargs):
            payload = json.loads(request.data)
            sent = json.loads(payload['messages'][1]['content'])
            self.assertTrue(sent['snippets'])
            self.assertNotIn('key', sent)
            return Response()
        settings = {'enabled': True, 'url': 'http://127.0.0.1:1/v1', 'model': 'fixture', 'key': ''}
        with patch.object(w, 'SCAN', self.scan), patch.object(w, 'API', settings), patch.object(w.urllib.request, 'urlopen', side_effect=respond):
            report = w.analyze_usage({'query': '解释输出变量用途'})
            self.assertEqual(report['api_calls'], 1)
            self.assertFalse(report['findings'][0]['selectable'])
        def stale(request, **kwargs):
            self.source.write_text(SOURCE+'\n// changed\n')
            return Response()
        with patch.object(w, 'SCAN', self.scan), patch.object(w, 'API', settings), patch.object(w.urllib.request, 'urlopen', side_effect=stale):
            with self.assertRaisesRegex(ValueError, '源码已变化'): w.analyze_usage({})


if __name__ == '__main__': unittest.main()
