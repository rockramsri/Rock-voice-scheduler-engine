// Mock nurse profiles for one-click injection while registering a workflow:
// the operator supplies a real phone number, the rest comes from here.

export interface MockProfile {
  name: string;
  specialties: string[];
  areas: string[];
  pay_level: number;
  license_ok: boolean;
}

export const MOCK_PROFILES: MockProfile[] = [
  { name: "Maria Alvarez", specialties: ["wound care"], areas: ["Jersey City"], pay_level: 3, license_ok: true },
  { name: "James Okafor", specialties: ["wound care"], areas: ["Hoboken"], pay_level: 2, license_ok: true },
  { name: "Fatima Diallo", specialties: ["wound care"], areas: ["Bayonne"], pay_level: 1, license_ok: true },
  { name: "Priya Natarajan", specialties: ["geriatric"], areas: ["Jersey City"], pay_level: 3, license_ok: true },
  { name: "Grace Lim", specialties: ["geriatric"], areas: ["Edison"], pay_level: 2, license_ok: true },
  { name: "Darnell Hayes", specialties: ["physical therapy"], areas: ["Hackensack"], pay_level: 3, license_ok: true },
  { name: "Elena Petrova", specialties: ["pediatric"], areas: ["Montclair"], pay_level: 2, license_ok: true },
  { name: "Hannah Weiss", specialties: ["physical therapy"], areas: ["Morristown"], pay_level: 2, license_ok: true },
];

export const ALL_CHANNELS = ["sms", "whatsapp", "voice"] as const;
