#include <esp_now.h>
#include <WiFi.h>

#define OLED
#define SERIALDEBUG

#define IDENTIFY 0x01
#define DISPLAY_DATA 0x10

#ifdef OLED
  #include <U8g2lib.h>
  #include <U8x8lib.h>
  // init OLED
  U8X8_SSD1306_128X64_NONAME_SW_I2C u8x8(/* clock=*/ 15, /* data=*/ 4, /* reset=*/ 16);
#endif

typedef struct struct_message {
  uint8_t command=0x22; 
  uint8_t pos;
  uint8_t lap;
  char text1[15];
  char text2[15];
  char text3[20];
} struct_message;

// Create a struct_message called myData
struct_message myData;

esp_now_peer_info_t peerInfo;

// callback when data is sent
void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  #ifdef SERIALDEBUG
    Serial.print("\r\nLast Packet Send Status:\t");
    Serial.println(status == ESP_NOW_SEND_SUCCESS ? "Delivery Success" : "Delivery Fail");
  #endif
  #ifdef OLED
  u8x8.setCursor(0, 0);
    u8x8.print(status == ESP_NOW_SEND_SUCCESS ? "Success" : "Fail");
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
  peerInfo.channel = 0;  
  peerInfo.encrypt = false;
  
  #ifdef OLED
    u8x8.begin();
    u8x8.setFont(u8x8_font_chroma48medium8_r);
    u8x8.print("Ready");
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
      u8x8.clear();
    #endif      

    if (receivedBytes[1] == IDENTIFY) {
      Serial.println(F("Fusion ESP"));
      #ifdef OLED
        u8x8.print("Identify");
      #endif        
    } else if (receivedBytes[1] == DISPLAY_DATA) {
      for(byte n = 0; n < 6; n++) {
        rcvAddress[n] = receivedBytes[n+2];
      }

      myData.pos = receivedBytes[8];
      myData.lap = receivedBytes[9];
      for(byte n = 0; n < 15; n++) {
        myData.text1[n] = receivedBytes[n+10];
      }
      for(byte n = 0; n < 15; n++) {
        myData.text2[n] = receivedBytes[n+25];
      }
      for(byte n = 0; n < 20; n++) {
        myData.text3[n] = receivedBytes[n+40];
      }
    
      // Show debug info
      #ifdef SERIALDEBUG
        for (byte n = 0; n < numReceived; n++) {
          Serial.print(receivedBytes[n], HEX);
          Serial.print(' ');
        }
        Serial.println(' ');
        Serial.println(myData.pos);
        Serial.println(myData.lap);
        Serial.println(myData.text1);
        Serial.println(myData.text2);
        Serial.println(myData.text3);
      #endif      

      #ifdef OLED
        u8x8.setCursor(0, 1);
        u8x8.print("Pos: ");
        u8x8.print(myData.pos);
        u8x8.setCursor(0, 2);
        u8x8.print("Lap: ");
        u8x8.print(myData.lap);
        u8x8.setCursor(0, 3);
        for(byte n = 0; n < 15; n++) {
          u8x8.print(myData.text1[n]);
        }    
        u8x8.setCursor(0, 4);
        for(byte n = 0; n < 15; n++) {
          u8x8.print(myData.text2[n]);
        }
        u8x8.setCursor(0, 5);
        for(byte n = 0; n < 16; n++) {
          u8x8.print(myData.text3[n]);
        }
        u8x8.setCursor(0, 7);
        u8x8.print("mac:");
        for(byte n = 0; n < 6; n++) {
          u8x8.print(rcvAddress[n], HEX);
        }
      #endif

      // Set peer
      memcpy(peerInfo.peer_addr, rcvAddress, 6);
      if (esp_now_add_peer(&peerInfo) != ESP_OK){
        #ifdef SERIALDEBUG
          Serial.println("Failed to add peer");
        #endif
        return;
      }

      // Send message via ESP-NOW
      esp_err_t result = esp_now_send(rcvAddress, (uint8_t *) &myData, sizeof(myData));

      if (result == ESP_OK) {
        #ifdef SERIALDEBUG
          Serial.println("Sent with success");
        #endif
      }
      else {
        #ifdef SERIALDEBUG
          Serial.println("Error sending the data");
        #endif
        #ifdef OLED
          u8x8.print("Error");
        #endif      
      }
      // Remove peer
      esp_now_del_peer(rcvAddress);
    } else {
      #ifdef SERIALDEBUG
        for (byte n = 0; n < numReceived; n++) {
          Serial.print(receivedBytes[n], HEX);
          Serial.print(" ");
        }
        Serial.println("");
        Serial.print("Command: ");
        Serial.println(receivedBytes[1]);
      #endif

      #ifdef OLED
        u8x8.clear();
        u8x8.setCursor(0, 0);
        u8x8.print("Command: ");
        u8x8.print(receivedBytes[1]);
      #endif
    }
  }
}  

void loop() {
    recvBytes();
    handleCommand();
}
