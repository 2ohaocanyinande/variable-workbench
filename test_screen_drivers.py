"""Behavior checks for line LCD and source-verified SPI text contracts."""
import unittest
import test_source_screen as base
import source_screen as s

LCD_DRIVER='''
#define Black 0x0000
#define White 0xFFFF
'''+''.join(f'#define Line{i} {i*24}\n' for i in range(10))+'''
static vu16 TextColor=0x0000,BackColor=0xFFFF;
void LCD_WriteRAM(int c){GPIOC->ODR=c;}
void LCD_DrawChar(u8 Xpos,u16 Ypos,uc16 *c){
 for(index=0;index<24;index++){for(i=0;i<16;i++){LCD_WriteRAM(TextColor);}}
}
void LCD_DisplayChar(u8 Line,u16 Column,u8 Ascii){LCD_DrawChar(Line,Column,&font[Ascii*24]);}
void LCD_DisplayStringLine(u8 Line,u8 *ptr){
 u16 refcolumn=319;while((*ptr!=0)&&(i<20)){LCD_DisplayChar(Line,refcolumn,*ptr);refcolumn-=16;ptr++;i++;}
}
void LCD_Clear(u16 Color){for(index=0;index<76800;index++){LCD_WriteRAM(Color);}}
'''
LCD_APP='''
uint8_t lcd_page=0,state=0;
float MIN=6.4,MAX=8.4;
void main(void){LCD_Clear(Black);LCD_SetBackColor(Black);LCD_SetTextColor(White);}
void Lcd_Porc(void){
 if(lcd_page==0){
  sprintf(buf,"BATTERY");LCD_DisplayStringLine(Line1,(uint8_t*)buf);
  sprintf(buf,"VOLT:%.1fV",PB15_volt);LCD_DisplayStringLine(Line3,(uint8_t*)buf);
  if(state==0){sprintf(buf,"IDLE");LCD_DisplayStringLine(Line4,(uint8_t*)buf);}
  else if(state==1){sprintf(buf,"CHARGE");LCD_DisplayStringLine(Line4,(uint8_t*)buf);}
 }else if(lcd_page==1){
  sprintf(buf,"SET");LCD_DisplayStringLine(Line1,(uint8_t*)buf);
  sprintf(buf,"MIN:%.1fV",MIN);LCD_DisplayStringLine(Line3,(uint8_t*)buf);
  sprintf(buf,"MAX:%.1fV",MAX);LCD_DisplayStringLine(Line4,(uint8_t*)buf);
 }
}
'''
SPI_DRIVER='''
#define LCD_W 240
#define LCD_H 135
#define WHITE 0xFFFF
#define BLACK 0
void LCD_WriteData(u8 byte){HAL_SPI_Transmit(&hspi1,&byte,1,100);}
void LCD_DrawPoint(u16 x,u16 y,u16 color){LCD_WriteData(color>>8);LCD_WriteData(color&255);}
void LCD_ShowChar(u16 x,u16 y,u8 ch,u16 fc,u16 bc,u8 size,u8 mode){
 for(i=0;i<size;i++){for(j=0;j<size/2;j++){LCD_DrawPoint(x+j,y+i,fc);}}
}
void LCD_ShowString(u16 x,u16 y,u8 *p,u16 fc,u16 bc,u8 size,u8 mode){
 while(*p){LCD_ShowChar(x,y,*p,fc,bc,size,mode);x+=size/2;p++;}
}
'''

class DisplayDriverTests(unittest.TestCase):
    setUp=base.SourceScreenTests.setUp
    make=base.SourceScreenTests.make
    render=base.SourceScreenTests.render
    def test_lcd_pages_buffer_cast_defaults_and_colors(self):
        self.make(LCD_DRIVER,LCD_APP)
        self.assertEqual(self.group['name'],'Lcd_Porc');self.assertFalse(any(g['name']=='if' for g in self.report['groups']))
        self.assertEqual(self.group['profile']['width'],320);self.assertEqual(self.group['profile']['colors']['foreground'],65535)
        self.assertEqual(self.group['defaults']['MIN']['value'],6.4);self.assertNotIn('buf',self.group['variables']);self.assertIn('PB15_volt',self.group['variables'])
        r=self.render(dict(lcd_page=0,state=0,PB15_volt=7.2));self.assertTrue(r['rows'][1].startswith('BATTERY'));self.assertTrue(r['rows'][3].startswith('VOLT:7.2V'));self.assertTrue(r['rows'][4].startswith('IDLE'));self.assertFalse(r['warnings'])
        r=self.render(dict(lcd_page=0,state=1,PB15_volt=7.2));self.assertTrue(r['rows'][4].startswith('CHARGE'))
        r=self.render(dict(lcd_page=1,MIN=6.4,MAX=8.4));self.assertTrue(r['rows'][1].startswith('SET'));self.assertTrue(r['rows'][3].startswith('MIN:6.4V'));self.assertFalse(r['warnings'])
        self.assertFalse(self.report['unsupported'])
    def test_plain_else_does_not_overlay_previous_page(self):
        self.make(LCD_DRIVER,'void draw(void){if(page==0){LCD_DisplayStringLine(Line0,"ONE");}else{LCD_DisplayStringLine(Line0,"TWO");}}')
        self.assertTrue(self.render({'page':0})['rows'][0].startswith('ONE'));self.assertTrue(self.render({'page':1})['rows'][0].startswith('TWO'))
    def test_external_key_toggle_is_traced_without_running_key_state_machine(self):
        self.make(LCD_DRIVER,LCD_APP+'\nvoid keys(void){if(key1.down){lcd_page=!lcd_page;key1.down=0;}}')
        b=self.group['buttons'][0];self.assertEqual(b['input'],'key1.down');self.assertEqual(b['variable'],'lcd_page');self.assertEqual(b['operation'],'toggle');self.assertEqual(b['path'],'main.c')
    def test_unknown_conditions_are_skipped(self):
        self.make(LCD_DRIVER,'void draw(void){if(flag>2){LCD_DisplayStringLine(Line0,"UNSAFE");}else{LCD_DisplayStringLine(Line0,"ELSE");}}')
        r=self.render({'flag':3});self.assertFalse(any(row.strip() for row in r['rows']));self.assertTrue(r['warnings'])
        self.make(LCD_DRIVER,'void draw(void){if(flag) LCD_DisplayStringLine(Line0,"IF");else LCD_DisplayStringLine(Line0,"ELSE");}')
        r=self.render({'flag':1});self.assertFalse(any(row.strip() for row in r['rows']));self.assertTrue(r['warnings'])
    def test_bus_independent_line_lcd_contract(self):
        self.make(LCD_DRIVER.replace('GPIOC->ODR=c;','HAL_SPI_Transmit(&hspi1,&c,1,100);'),LCD_APP)
        self.assertEqual(self.group['profile']['transport'],'SPI');self.assertTrue(self.render(dict(lcd_page=0,state=0,PB15_volt=7.2))['rows'][3].startswith('VOLT:7.2V'))
    def test_spi_pixel_coordinates_font_and_rgb565(self):
        self.make(SPI_DRIVER,'void draw(void){sprintf(buf,"A:%.1f",angle);LCD_ShowString(12,24,buf,WHITE,BLACK,24,0);}')
        self.assertTrue(self.group['grid_verified']);self.assertEqual(self.group['profile']['transport'],'SPI');r=self.render({'angle':12.5});draw=r['draws'][0]
        self.assertEqual((draw['x'],draw['y'],draw['font_width'],draw['font_height']),(12,24,12,24));self.assertEqual(draw['text'],'A:12.5');self.assertEqual(draw['foreground'],'#ffffff');self.assertFalse(r['warnings'])
        self.make(SPI_DRIVER,'void draw(void){LCD_ShowString(0,0,(uint8_t*)"SPI SCREEN",WHITE,BLACK,16,0);}')
        self.assertEqual(self.render({})['draws'][0]['text'],'SPI SCREEN')
    def test_spi_name_without_driver_contract_does_not_invent_display(self):
        self.make(SPI_DRIVER.replace('x+=size/2','x+=size'),'void draw(void){LCD_ShowString(0,0,"TEST",WHITE,BLACK,16,0);}')
        self.assertFalse(self.group['grid_verified']);self.assertFalse(self.render({})['rows'])
    def test_hex_f_is_not_a_float_suffix(self):
        for expr in ['0xFFFF','0xFFFFU','0xFFFUL','1.0f','1e2F']:
            self.assertEqual(s.evaluate(expr,{}),{'0xFFFF':65535,'0xFFFFU':65535,'0xFFFUL':4095,'1.0f':1,'1e2F':100}[expr])
    def test_file_scope_zero_initialization_has_source_and_excludes_extern_local_members(self):
        self.make(LCD_DRIVER,'''uint8_t page,line_flag;
extern
uint8_t external;
typedef struct { uint8_t member; } Clock;
void draw(void){uint8_t local;LCD_DisplayStringLine(Line0,"HELLO");}''')
        sources={p:(self.root/p).read_text(encoding='utf-8') for p in ('main.c','driver.c')}
        defs=s.screen_drivers.functions(sources);initial=s.initial_values(sources,defs,s.constant_index(sources))
        self.assertEqual(initial['page']['value'],0);self.assertEqual(initial['line_flag']['origin'],'zero');self.assertEqual(initial['page']['line'],1)
        for name in ('external','local','member'):self.assertNotIn(name,initial)
    def test_single_statement_highlight_and_three_pages(self):
        self.make(LCD_DRIVER+ '\n#define Green 0x07E0\n','''uint8_t page,line_flag;
void draw(void){
 if(page==0) LCD_DisplayStringLine(Line0,"HELLO");
 else if(page==1){
  if(line_flag==0) LCD_SetTextColor(Green); else LCD_SetTextColor(White);
  LCD_DisplayStringLine(Line3,"ONE");
  if(line_flag==1) LCD_SetTextColor(Green); else LCD_SetTextColor(White);
  LCD_DisplayStringLine(Line4,"TWO");
 }else LCD_DisplayStringLine(Line4,"THREE");
}''')
        for flag in (0,1):
            r=self.render({'page':1,'line_flag':flag});self.assertFalse(r['warnings']);self.assertEqual([d['foreground'] for d in r['draws']],['#00ff00','#ffffff'] if flag==0 else ['#ffffff','#00ff00'])
        r=self.render({'page':2});self.assertFalse(r['warnings']);self.assertTrue(r['rows'][4].startswith('THREE'));self.assertFalse(r['rows'][3].strip())
    def test_dangling_else_binds_inner_if(self):
        self.make(LCD_DRIVER,'void draw(void){if(page==0) if(highlight==0) LCD_DisplayStringLine(Line0,"INNER");else LCD_DisplayStringLine(Line0,"ELSE");}')
        self.assertTrue(self.render(dict(page=0,highlight=0))['rows'][0].startswith('INNER'))
        self.assertTrue(self.render(dict(page=0,highlight=1))['rows'][0].startswith('ELSE'))
        r=self.render(dict(page=1));self.assertFalse(r['rows'][0].strip());self.assertFalse(r['warnings'])
    def test_member_paths_are_one_input_and_read_only_numeric_lookup(self):
        self.make(LCD_DRIVER,'void draw(void){sprintf(buf,"Date:%02d-%02d",rtc_date.Year,rtc_date.Month);LCD_DisplayStringLine(Line1,buf);}')
        self.assertEqual(self.group['variables'],['rtc_date.Month','rtc_date.Year'])
        self.assertTrue(self.render({'rtc_date.Year':25,'rtc_date.Month':12})['rows'][1].startswith('Date:25-12'))
        self.assertIsNone(s.evaluate('object.__class__',{'object.__class__':7}));self.assertIsNone(s.evaluate('getter().Year',{}))
    def test_missing_page_warning_names_input_once(self):
        self.make(LCD_DRIVER,LCD_APP)
        warnings=self.render({})['warnings'];self.assertEqual(len(warnings),1);self.assertIn('lcd_page',warnings[0]);self.assertNotIn('main.c:',warnings[0])

if __name__=='__main__':
    import unittest
    unittest.main()
