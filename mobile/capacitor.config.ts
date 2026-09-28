import type { CapacitorConfig } from "@capacitor/cli";

const config: CapacitorConfig = {
  appId: "ru.buildvision.app",
  appName: "BuildVision",
  webDir: "dist",
  loggingBehavior: "none",
  backgroundColor: "#0b0f1a",
  android: {
    allowMixedContent: false,
    webContentsDebuggingEnabled: false,
  },
};

export default config;
