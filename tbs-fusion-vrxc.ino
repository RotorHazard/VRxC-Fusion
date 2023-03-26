#include <esp_now.h>
#include <WiFi.h>

#define OLED

#define READY_HEAT 0x00
#define JOIN_ADDRESS 0x01
#define LAP_DATA 0x10

#ifdef OLED
  #include <U8g2lib.h>
  #include <U8x8lib.h>
  // init OLED
  U8X8_SSD1306_128X64_NONAME_SW_I2C u8x8(/* clock=*/ 15, /* data=*/ 4, /* reset=*/ 16);
#endif

uint32_t x = 0;
// REPLACE WITH YOUR RECEIVER MAC Address
uint8_t broadcastAddress[] = {0x48, 0x3F, 0xDA, 0x49, 0xA6, 0xB9};

// Structure example to send data
// Must match the receiver structure
typedef struct struct_message {
  uint32_t seat_position;
  uint32_t lap_number;
  uint32_t current_lap_time;
  uint32_t last_lap_time;
  uint32_t nanumber;
  char freetext[32];
} struct_message;

// Create a struct_message called myData
struct_message myData;

esp_now_peer_info_t peerInfo;

// callback when data is sent
void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  Serial.print("\r\nLast Packet Send Status:\t");
  Serial.println(status == ESP_NOW_SEND_SUCCESS ? "Delivery Success" : "Delivery Fail");
  #ifdef OLED
    u8x8.clear();
    u8x8.draw2x2String(0, 0, status == ESP_NOW_SEND_SUCCESS ? "Success" : "Fail");
    u8x8.drawString(0, 2, myData.freetext);
    u8x8.setCursor(0, 3);
    u8x8.print(myData.seat_position);
    u8x8.setCursor(0, 4);
    u8x8.print(myData.lap_number);
    u8x8.setCursor(0, 5);
    u8x8.print(myData.current_lap_time);
    u8x8.setCursor(0, 6);
    u8x8.print(myData.last_lap_time);
  #endif
}
 
void setup() {
  // Init Serial Monitor
  Serial.begin(115200);
 
  // Set device as a Wi-Fi Station
  WiFi.mode(WIFI_STA);

  // Init ESP-NOW
  if (esp_now_init() != ESP_OK) {
    Serial.println("Error initializing ESP-NOW");
    return;
  }

  // Once ESPNow is successfully Init, we will register for Send CB to
  // get the status of Trasnmitted packet
  esp_now_register_send_cb(OnDataSent);
  
  // Register peer
  memcpy(peerInfo.peer_addr, broadcastAddress, 6);
  peerInfo.channel = 0;  
  peerInfo.encrypt = false;
  
  // Add peer        
  if (esp_now_add_peer(&peerInfo) != ESP_OK){
    Serial.println("Failed to add peer");
    return;
  }

  #ifdef OLED
    u8x8.begin();
    u8x8.setFont(u8x8_font_chroma48medium8_r);
    u8x8.print("ready");
  #endif
}

const byte numBytes = 255;
byte receivedBytes[numBytes];
byte numReceived = 0;
boolean newData = false;
char freetextStr[32];

void recvBytes() {
    static boolean recvInProgress = false;
    static byte ndx = 0;
    static int dataLen = 0;
    byte rb;  

    while (Serial.available() > 0 && newData == false) {
        rb = Serial.read();

        if (ndx > 0) {
          dataLen = receivedBytes[0];
        }
        
        if (recvInProgress == true) {
            if (dataLen == 0 || ndx < dataLen + 1) {
                receivedBytes[ndx] = rb;
                ndx++;
                if (ndx >= numBytes) {
                    ndx = numBytes - 1;
                }
            }
            else {
                receivedBytes[ndx] = '\0'; // terminate the string
                recvInProgress = false;
                numReceived = ndx;  // save the number for use when printing
                ndx = 0;
                dataLen = 0;
                newData = true;
            }
        }

        else if (rb == 0x00) {
            recvInProgress = true;
            #ifdef OLED
              u8x8.print("receive");
            #endif
        }
    }
}

byte rcvAddress[6];

void handleCommand() {
  if (newData == true) {
    newData = false;

    #ifdef OLED
      u8x8.print("process");
    #endif

    for (byte n = 0; n < numReceived; n++) {
      Serial.print(receivedBytes[n], HEX);
      Serial.print(' ');
    }
    Serial.println(' ');
    
    for(byte n = 0; n < 6; n++) {
      rcvAddress[n] = receivedBytes[n+2];
    }
    
    myData.seat_position = ((long)receivedBytes[8] << 24 | (long)receivedBytes[9] << 16 | (long)receivedBytes[10] << 8 | receivedBytes[11]);
    myData.lap_number = ((long)receivedBytes[12] << 24 | (long)receivedBytes[13] << 16 | (long)receivedBytes[14] << 8 | receivedBytes[15]);
    myData.current_lap_time = ((long)receivedBytes[16] << 24 | (long)receivedBytes[17] << 16 | (long)receivedBytes[18] << 8 | receivedBytes[19]);
    myData.last_lap_time = ((long)receivedBytes[20] << 24 | (long)receivedBytes[21] << 16 | (long)receivedBytes[22] << 8 | receivedBytes[23]);

    for(byte n = 0; n < numReceived - 23; n++) {
      freetextStr[n] = receivedBytes[n+24];
    }
    Serial.println(freetextStr);
    strcpy(myData.freetext, "");
    strncpy(myData.freetext, freetextStr, strlen(freetextStr));
     
    // Send message via ESP-NOW
    esp_err_t result = esp_now_send(rcvAddress, (uint8_t *) &myData, sizeof(myData));
     
    if (result == ESP_OK) {
      Serial.println("Sent with success");
    }
    else {
      Serial.println("Error sending the data");
    }
  }
}  

void loop() {
    recvBytes();
    handleCommand();
}
