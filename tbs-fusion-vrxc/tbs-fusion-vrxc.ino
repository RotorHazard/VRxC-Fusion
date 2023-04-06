#include <esp_now.h>
#include <WiFi.h>

#define LED_BUILTIN 2
// #define OLED
// #define SERIALDEBUG

#define IDENTIFY 0x01
#define DISPLAY_DATA 0x10

#define MAX_RETRY 5
#define BAUDRATE 921600

#ifdef OLED
  #include <U8g2lib.h>
  #include <U8x8lib.h>
  // init OLED
  U8X8_SSD1306_128X64_NONAME_SW_I2C u8x8(/* clock=*/ 15, /* data=*/ 4, /* reset=*/ 16);
#endif

// data structure
byte rcvAddress[6];
typedef struct struct_message {
  uint8_t cc = 0x22;
  uint8_t pos;
  uint8_t lap;
  char text1[16];
  char text2[16];
  char text3[21];
} struct_message;

struct_message fusionOsdFrame;

esp_now_peer_info_t peerInfo;
esp_now_peer_num_t peer_num;
    
uint8_t tries;

// callback when data is sent
void OnDataSent(const uint8_t *mac_addr, esp_now_send_status_t status) {
  tries++;
  if (status == ESP_NOW_SEND_SUCCESS) {
    esp_now_del_peer(mac_addr);
    #ifdef SERIALDEBUG
      Serial.print(F("Last Packet Send Status:\t"));
      Serial.println(F("Delivery Success"));
    #endif
    #ifdef OLED
      u8x8.setCursor(0, 0);
      u8x8.print("Success / ");
      u8x8.print(tries);
    #endif
  } else {
    if (tries <= MAX_RETRY) {
      #ifdef SERIALDEBUG
        Serial.print(F("Last Packet Send Status:\t"));
        Serial.println(F("Delivery Fail"));
      #endif   
      #ifdef OLED
        u8x8.setCursor(0, 0);
        u8x8.print("Fail / ");
        u8x8.print(tries);
      #endif
      esp_now_send(mac_addr, (uint8_t *) &fusionOsdFrame, sizeof(fusionOsdFrame));
    } else {
      esp_now_del_peer(mac_addr);
      #ifdef SERIALDEBUG
        Serial.println(F("No more retries"));
      #endif
      #ifdef OLED
        u8x8.print("*");
      #endif        
    }
  }

  // LED off when no peers exist
  esp_now_get_peer_num (&peer_num);
  if (!peer_num.total_num) {
    digitalWrite(LED_BUILTIN, LOW);
  }
}

void setup() {
  // Init Serial Monitor
  Serial.begin(BAUDRATE);
 
  // Set device as a Wi-Fi Station
  WiFi.mode(WIFI_STA);
  /*
  WiFi.softAP("RACE_SERVER", "", 1, 0, 4, false);
  #ifdef SERIALDEBUG
    Serial.print("Station IP Address: ");
    Serial.println(WiFi.localIP());
    Serial.print("Wi-Fi Channel: ");
    Serial.println(WiFi.channel());
  #endif
  */
  
  // Init ESP-NOW
  if (esp_now_init() != ESP_OK) {
    Serial.println(F("Error initializing ESP-NOW"));
    return;
  }

  // Once ESPNow is successfully Init, we will register for Send CB to
  // get the status of Trasnmitted packet
  esp_now_register_send_cb(OnDataSent);
  
  // Start peer config
  // Set peer
  peerInfo.channel = 1;  
  peerInfo.encrypt = false;
  
  #ifdef OLED
    u8x8.begin();
    u8x8.setFont(u8x8_font_chroma48medium8_r);
    u8x8.print(F("Ready"));
  #endif

  // blink LED 3× at startup, leave on
  pinMode(LED_BUILTIN, OUTPUT);
  for(int i = 0; i < 3; i++) {
    digitalWrite(LED_BUILTIN, LOW);
    delay(100);
    digitalWrite(LED_BUILTIN, HIGH);
    delay(100);
  }
}

const byte maxBytes = 255;
byte receivedBytes[maxBytes];
byte numReceived = 0;
boolean newData = false;

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
                if (ndx >= maxBytes) {
                    ndx = maxBytes - 1;
                }
            }
            else {
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
              u8x8.print(F("--receive--"));
            #endif
        }
    }
}

void handleCommand() {
  if (newData == true) {
    newData = false;

    #ifdef OLED
      u8x8.clear();
    #endif      

    if (receivedBytes[1] == IDENTIFY) {
      Serial.println(F("Fusion ESP"));
      #ifdef OLED
        u8x8.print(F("Identify"));
      #endif

      // blink LED 3× at identify, leave off
      for(int i = 0; i < 3; i++) {
        digitalWrite(LED_BUILTIN, HIGH);
        delay(100);
        digitalWrite(LED_BUILTIN, LOW);
        delay(100);
      }
    } else if (receivedBytes[1] == DISPLAY_DATA) {
      for(byte n = 0; n < 6; n++) {
        rcvAddress[n] = receivedBytes[n+2];
      }

      fusionOsdFrame.pos = receivedBytes[8];
      fusionOsdFrame.lap = receivedBytes[9];

      for(byte n = 0; n < 15; n++) {
        fusionOsdFrame.text1[n] = receivedBytes[n+10];
      }
      fusionOsdFrame.text1[15] = '\0';
      for(byte n = 0; n < 15; n++) {
        fusionOsdFrame.text2[n] = receivedBytes[n+26];
      }
      fusionOsdFrame.text2[15] = '\0';
      for(byte n = 0; n < 20; n++) {
        fusionOsdFrame.text3[n] = receivedBytes[n+42];
      }
      fusionOsdFrame.text3[20] = '\0';

          
      // Show debug info
      #ifdef SERIALDEBUG
        for (byte n = 0; n < numReceived; n++) {
          Serial.print(receivedBytes[n], HEX);
          Serial.print(' ');
        }
        Serial.println(' ');
        Serial.println(fusionOsdFrame.pos);
        Serial.println(fusionOsdFrame.lap);
        Serial.println(fusionOsdFrame.text1);
        Serial.println(fusionOsdFrame.text2);
        Serial.println(fusionOsdFrame.text3);
      #endif      

      #ifdef OLED
        u8x8.setCursor(0, 1);
        u8x8.print(F("Pos: "));
        u8x8.print(fusionOsdFrame.pos);
        u8x8.setCursor(0, 2);
        u8x8.print(F("Lap: "));
        u8x8.print(fusionOsdFrame.lap);
        u8x8.setCursor(0, 3);
        for(byte n = 0; n < 15; n++) {
          u8x8.print(fusionOsdFrame.text1[n]);
        }    
        u8x8.setCursor(0, 4);
        for(byte n = 0; n < 15; n++) {
          u8x8.print(fusionOsdFrame.text2[n]);
        }
        u8x8.setCursor(0, 5);
        for(byte n = 0; n < 16; n++) {
          u8x8.print(fusionOsdFrame.text3[n]);
        }
        u8x8.setCursor(0, 7);
        u8x8.print(F("mac:"));
        for(byte n = 0; n < 6; n++) {
          u8x8.print(rcvAddress[n], HEX);
        }
      #endif

      // LED on when peers exist
      digitalWrite(LED_BUILTIN, HIGH);
      
      // Set peer
      memcpy(peerInfo.peer_addr, rcvAddress, 6);
      if (esp_now_add_peer(&peerInfo) != ESP_OK){
        #ifdef SERIALDEBUG
          Serial.println(F("Failed to add peer"));
        #endif
        return;
      }

      // Send message via ESP-NOW
      tries = 0;
      esp_err_t result = esp_now_send(rcvAddress, (uint8_t *) &fusionOsdFrame, sizeof(fusionOsdFrame));

      if (result == ESP_OK) {
        #ifdef SERIALDEBUG
          Serial.println(F("Sent with success"));
        #endif
      } else {
        #ifdef SERIALDEBUG
          Serial.println(F("Error sending the data"));
        #endif
        #ifdef OLED
          u8x8.print(F("Error"));
        #endif      
      }
    } else {
      #ifdef SERIALDEBUG
        for (byte n = 0; n < numReceived; n++) {
          Serial.print(receivedBytes[n], HEX);
          Serial.print(" ");
        }
        Serial.println("");
        Serial.print(F("Command: "));
        Serial.println(receivedBytes[1], HEX);
      #endif

      #ifdef OLED
        u8x8.clear();
        u8x8.setCursor(0, 0);
        u8x8.print(F("Command: "));
        u8x8.print(receivedBytes[1], HEX);
      #endif
    }
  }
}  

void loop() {
    recvBytes();
    handleCommand();
}
