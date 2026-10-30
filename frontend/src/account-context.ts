import { createContext, useContext } from "react";

export type AccountUser = {
  id: string;
  username: string;
  display_name: string;
  is_admin: boolean;
  enabled: boolean;
  mfa_enabled: boolean;
  recovery_required?: boolean;
  created_at: string;
};
export type AccountStatus = {
  authenticated: boolean;
  setup_required: boolean;
  user: AccountUser | null;
  expires_at?: string | null;
};
export const AccountContext = createContext<{
  mode: "accounts" | "operator";
  user?: AccountUser;
  signOut?: () => Promise<void>;
}>({ mode: "operator" });
export const useAccount = () => useContext(AccountContext);
