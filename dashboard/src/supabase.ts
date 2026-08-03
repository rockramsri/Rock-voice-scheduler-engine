// Supabase browser client. The publishable (anon) key is public by design;
// RLS policies in data/dashboard.sql decide what it can see and touch.
import { createClient } from "@supabase/supabase-js";

const url =
  import.meta.env.VITE_SUPABASE_URL ?? "https://xzcpacifagkkxlplocgu.supabase.co";
const key =
  import.meta.env.VITE_SUPABASE_ANON_KEY ??
  "sb_publishable_bAjmPr7lb8fSJnyWzS9T8w_fjXLexkE";

export const supabase = createClient(url, key);
