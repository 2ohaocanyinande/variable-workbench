// Software parser fixture only; this is not a hardware driver.

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
