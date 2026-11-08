// Parsing fixture only. Presence of this code does not prove physical hardware.
void sample_imu(void) {
    HAL_I2C_Mem_Read(&hi2c1,LSM6DSR_ADDRESS_FROM_BOARD_CONFIG,REGISTER_FROM_DRIVER,ADDRESS_SIZE,buffer,6,100);
}
