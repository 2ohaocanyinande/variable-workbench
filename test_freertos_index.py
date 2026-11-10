from pathlib import Path
import tempfile
import unittest

import workbench as w


class FreeRTOSIndexTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(dir=w.BASE)
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.write('board.ioc', 'Mcu.Name=STM32F103C8Tx\n')

    def write(self, name, text):
        path = self.root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(text,encoding='utf-8')

    def test_native_and_cmsis_tasks_have_correct_stack_units_and_evidence(self):
        self.write('board.ioc','Mcu.Name=STM32F103C8Tx\nMcu.IP2=FREERTOS\n')
        self.write('FreeRTOS/App/app_freertos.c','''#include "cmsis_os2.h"
const osThreadAttr_t worker_attrs = {
    .name = "worker, main",
    .priority = osPriorityNormal,
    .stack_size = 128 * 4,
};
void Worker(void *arg) {}
void Poll(void *arg) {}
void setup(void) {
    xTaskCreate(Poll, "poll", 128, NULL, 2, NULL);
    worker = osThreadNew(Worker, NULL, &worker_attrs);
    queue = osMessageQueueNew(8, sizeof(uint16_t), NULL);
    lock = xSemaphoreCreateMutex();
    osKernelStart();
}
''')
        self.write('Middlewares/Third_Party/FreeRTOS/Source/vendor.c','void fake(void) { xTaskCreate(Fake,"bad",1,0,1,0); }\n')
        scan=w.scan_project(self.root)
        report=scan['rtos']
        native,cmsis=report['tasks']
        self.assertEqual((native['entry'],native['stack'],native['stack_unit']),('Poll','128','StackType_t 元素'))
        self.assertEqual((cmsis['name'],cmsis['stack'],cmsis['stack_unit']),('worker, main','128 * 4','字节'))
        self.assertEqual(cmsis['evidence'][2]['line'],7)
        self.assertEqual([r['kind'] for r in report['objects']],['队列','互斥锁'])
        self.assertEqual(report['scheduler'][0]['api'],'osKernelStart')
        self.assertTrue(all(e['sha256']==scan['files'][e['path']] for row in report['tasks'] for e in row['evidence']))

    def test_cmsis_v1_and_backend_unknown(self):
        self.write('main.c','''#include "cmsis_os.h"
osThreadDef(Default, StartDefault, osPriorityNormal, 0, 128);
void StartDefault(void *arg) {}
void start(void) {
    handle = osThreadCreate(osThread(Default), NULL);
}
''')
        report=w.scan_project(self.root)['rtos']
        self.assertIn('内核待核对',report['status'])
        self.assertEqual(report['tasks'][0]['entry'],'StartDefault')
        self.assertEqual(report['tasks'][0]['stack_unit'],'按 v1 封装核对')

    def test_comment_and_kernel_only_do_not_count_as_created_task(self):
        self.write('main.c','''/*
#include "FreeRTOS.h"
*/
void main(void) {
    // xTaskCreate(Task, "fake", 64, NULL, 2, NULL);
}
''')
        self.assertIn('未发现',w.scan_project(self.root)['rtos']['status'])
        self.write('FreeRTOS/Target/FreeRTOSConfig.h','#define configTICK_RATE_HZ 1000\n')
        report=w.scan_project(self.root)['rtos']
        self.assertIn('FreeRTOS 线索',report['status'])
        self.assertFalse(report['tasks'])
