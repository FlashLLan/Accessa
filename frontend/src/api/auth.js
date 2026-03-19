import client from "./client";

export async function loginRequest({ email, password }) {
  const response = await client.post("/auth/login", {
    email,
    password,
  });

  return response.data;
}
