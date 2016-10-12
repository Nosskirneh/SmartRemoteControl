#include <RCSwitch.h>
#include <ctype.h>
#include "IRremote_library.h"
#include "IRremoteInt_library.h"

// Pin connected to the IR receiver.
#define IR_RECV_PIN 11

// Length of time to delay between codes.
#define REPEAT_DELAY_MS 40

// Size of parsing buffer.
#define BUFFER_SIZE 100

// Parsing state.
char buffer[BUFFER_SIZE+1] = {0};
int index = 0;
decode_results command;
unsigned int rawbuf[RAWBUF] = {0};

// Remote code types.
#define TYPE_COUNT 10
String type_names[TYPE_COUNT] = { "NEC", "SONY", "RC5", "RC6", "DISH", "SHARP", "PANASONIC", "JVC", "MHZ433", "RAW" };
int type_values[TYPE_COUNT] = { 1, 2, 3, 4, 5, 6, 7, 8, 9, -1 };

long int mhz_codes[4][2] = {
  {5510485, 5510484},
  {5522773, 5522772},
  {5525845, 5525844},
  {5526613, 5526612},
};

// IR send and receive class.
IRsend irsend;
IRrecv irrecv(IR_RECV_PIN);

// 433 MHz class and init
RCSwitch MHZ = RCSwitch();


// Setup function called once at bootup.
void setup() {
  // Initialize Serial and IR receiver.
  Serial.begin(9600);
  irrecv.enableIRIn();

  
  // Transmitter is connected to Arduino Pin #10
  MHZ.enableTransmit(10);
  // Optional set pulse length.
  MHZ.setPulseLength(420);
  // Optional set protocol (default is 1, will work for most outlets)
  MHZ.setProtocol(1);
  // Optional set number of transmission repetitions.
  MHZ.setRepeatTransmit(4);
}

// Loop function called continuously.
void loop() {
  // Check if any data is available and parse it.
  if (Serial.available() > 0) {
    // Read a character at a time.
    char c = Serial.read();
    if (c == ':') {
      // Parse remote code type as current buffer value when colon is found.
      String type = current_word();
      for (int i = 0; i < TYPE_COUNT; ++i) {
        if (type == type_names[i]) {
          command.decode_type = type_values[i];
        }
      }
    }
    else if (c == ' ' && command.decode_type == MHZ433) {
      char* c = current_word();
      //Serial.println(c);
      //Serial.println(sizeof(c));
      if (strcmp(c, "ON") == 0) {
        //Serial.println("Received on");
        command.powerCMD = "ON";
      } else if (strcmp(c, "OFF") == 0) {
        //Serial.println("Received off");
        command.powerCMD = "OFF";
      }
    }
    else if (c == ' ' && command.decode_type == PANASONIC && command.panasonicAddress == 0 && index > 0) {
      // Parse panasonic address as first value before whitespace.
      command.panasonicAddress = (unsigned int)strtoul(current_word(), NULL, 16);
    }
    else if (c == ' ' && command.decode_type != UNKNOWN && command.decode_type != PANASONIC && command.bits == 0 && index > 0) {
      // Parse number of bits as first value before whitespace.
      command.bits = (int)strtol(current_word(), NULL, 16);
    }
    else if (c == ' ' && command.decode_type == UNKNOWN && index > 0) {
      // Parse mark/space length as value for unknown/raw code.
      if (command.rawlen < RAWBUF) {
        rawbuf[command.rawlen] = (unsigned int)strtoul(current_word(), NULL, 16);
        command.rawlen++;
      }
    }
    else if (c == '\n' || c == ';') {
      // Finish parsing command when end of line received.
      // Parse remaining data in buffer.
      if (index > 0) {
        // Grab buffer data as IR code value.
        command.value = strtoul(current_word(), NULL, 16);
        // Move buffer data to raw code array if parsing unknown/raw code.
        if (command.decode_type == UNKNOWN && command.rawlen < RAWBUF) {
          rawbuf[command.rawlen] = (unsigned int)command.value;
          command.value = 0;
          command.rawlen++;
        }
      }
      // Print code to be sent.
      Serial.println("Sending remote code:");
      int type_index = command.decode_type > 0 ? command.decode_type - 1 : TYPE_COUNT - 1;
      Serial.print("Type: "); Serial.println(type_names[type_index]);
      if (command.panasonicAddress != 0) {
        Serial.print("Address: "); Serial.println(command.panasonicAddress, HEX);
      }
      if (command.powerCMD) {
        Serial.print("Command: "); Serial.println(command.powerCMD);
      }
      Serial.print("Value: "); Serial.println(command.value, HEX);
      if (command.rawlen > 0) {
        Serial.println("Raw value: ");
        for (int i = 0; i < command.rawlen; ++i) {
          Serial.print(rawbuf[i], HEX);
          Serial.print(" ");
        }
        Serial.println("");
      }
      Serial.println("--------------------");
      // Send code.
      send_command();
      // Enable IR receiver again.
      irrecv.enableIRIn();
      // Clear the command to prepare for parsing again.
      command = decode_results();
    }
    else if (c != ' ' && c != '\n' && c != '\t') {
      // Add non-whitespace characters to the buffer.
      buffer[index] = toupper(c);
      index = index == (BUFFER_SIZE-1) ? 0 : index+1;
    }
  }
  // Check if an IR code has been received and print it.
  decode_results results;
  if (irrecv.decode(&results)) {
    Serial.println("Decoded remote code:");
    print_code(&results);
    Serial.println("--------------------");
    delay(20);
    irrecv.resume();
  }
  // Wait a small amount so the Bridge library is not overwhelmed with requests to read the Serial.
  delay(10);
}

// Send the parsed remote control command.
void send_command() {
  // Use the right send function depending on the command type.
  if (command.decode_type == NEC) {
    irsend.sendNEC(command.value, command.bits);
  }
  else if (command.decode_type == SONY) {
    // Sony codes are sent 3 times as a part of their protocol.
    for (int i = 0; i < 3; ++i) {
      irsend.sendSony(command.value, command.bits);
      delay(REPEAT_DELAY_MS);
    }
  }
  else if (command.decode_type == MHZ433) {
    sendMHZ(command.value, command.powerCMD);
  }
  else if (command.decode_type == RC5) {
    // RC5 codes are sent 3 times as a part of their protocol.
    for (int i = 0; i < 3; ++i) {
      irsend.sendRC5(command.value, command.bits);
      delay(REPEAT_DELAY_MS);
    }
  }
  else if (command.decode_type == RC6) {
    // RC6 codes are sent 3 times as a part of their protocol.
    for (int i = 0; i < 3; ++i) {
      irsend.sendRC6(command.value, command.bits);
      delay(REPEAT_DELAY_MS);
    }
  }
  else if (command.decode_type == DISH) {
    irsend.sendDISH(command.value, command.bits);
  }
  else if (command.decode_type == SHARP) {
    irsend.sendSharp(command.value, command.bits);
  }
  else if (command.decode_type == PANASONIC) {
    irsend.sendPanasonic(command.panasonicAddress, command.value);
    delay(REPEAT_DELAY_MS);
  }
  else if (command.decode_type == JVC) {
    irsend.sendJVC(command.value, command.bits, 0);
  }
  else if (command.decode_type == UNKNOWN) {
    irsend.sendRaw(rawbuf, command.rawlen, 38);
  }
}

// Print received code to the Serial.
void print_code(decode_results *results) {
  if (results->decode_type == NEC) {
    Serial.print("NEC: ");
    Serial.print(results->bits, HEX);
    Serial.print(" ");
    Serial.println(results->value, HEX);
  }
  else if (results->decode_type == SONY) {
    Serial.print("SONY: ");
    Serial.print(results->bits, HEX);
    Serial.print(" ");
    Serial.println(results->value, HEX);
  }
  else if (results->decode_type == RC5) {
    Serial.print("RC5: ");
    Serial.print(results->bits, HEX);
    Serial.print(" ");
    Serial.println(results->value, HEX);
  }
  else if (results->decode_type == RC6) {
    Serial.print("RC6: ");
    Serial.print(results->bits, HEX);
    Serial.print(" ");
    Serial.println(results->value, HEX);
  }
  else if (results->decode_type == PANASONIC) {	
    Serial.print("PANASONIC: ");
    Serial.print(results->panasonicAddress,HEX);
    Serial.print(" ");
    Serial.println(results->value, HEX);
  }
  else if (results->decode_type == JVC) {
     Serial.print("JVC: ");
     Serial.print(results->bits, HEX);
     Serial.print(" ");
     Serial.println(results->value, HEX);
  }
  else if (results->decode_type == MHZ433) {
    Serial.print("MHZ433: ");
    Serial.print(results->value);
    Serial.print(" ");
    Serial.println(results->powerCMD);
  } 
  else {
    Serial.print("RAW: ");
    for (int i = 1; i < results->rawlen; i++) {
      // Scale length to microseconds.
      unsigned int value = results->rawbuf[i]*USECPERTICK;
      // Adjust length based on error in IR receiver measurement time.
      if (i % 2) {
        value -= MARK_EXCESS;
      }
      else {
        value += MARK_EXCESS;
      }
      // Print mark/space length.
      Serial.print(value, HEX);
      Serial.print(" ");
    }
    Serial.println("");
  }
}

// Grab the currently parsed word and clear the buffer.
char* current_word() {
  buffer[index] = 0;
  index = 0;
  //Serial.println(buffer);
  return buffer;
}

void sendMHZ(unsigned long device, char* power) {
  if (strcmp(power, "ON") == 0) {
    MHZ.send(mhz_codes[device-1][0], 24);
  } else if (strcmp(power, "OFF") == 0) {
    MHZ.send(mhz_codes[device-1][1], 24);
  }
}

