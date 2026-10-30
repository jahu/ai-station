export type SpeechDelivery = {
  exaggeration: number;
  cfg_weight: number;
  temperature: number;
};

export const defaultSpeechDelivery: SpeechDelivery = {
  exaggeration: 0.8,
  cfg_weight: 0.4,
  temperature: 0.6,
};

export type SpeechCapabilities = {
  available?: boolean;
  delivery?: { version: string } | null;
  engines?: {
    fish_s2_pro?: {
      available: boolean;
      readiness: string;
      reason?: string;
      license_url?: string;
    };
  };
};

export const speechDirections = [
  ["natural", "Natural"],
  ["whisper", "Whisper"],
  ["happy", "Happy"],
  ["sad", "Sad"],
  ["afraid", "Afraid"],
  ["angry", "Angry"],
  ["calm", "Calm"],
  ["excited", "Excited"],
  ["breathy", "Breathy"],
  ["sighing", "With sighs"],
] as const;
