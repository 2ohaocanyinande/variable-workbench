// Parsing contract fixture, not flashable firmware. Row/column convention is explicit.
void OLED_ShowChar(int Line,int Column,char c) {
    OLED_SetCursor((Line-1)*2,(Column-1)*8);
}
