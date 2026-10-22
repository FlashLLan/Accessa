import { useContext } from "react";
import { AuthContext } from "../context/authContextObject";

export const useAuth = () => {
  return useContext(AuthContext);
};