import client from "./client";

export async function loginRequest({ email, password }) {
  const response = await client.post("/auth/login", {
    email,
    password,
  });

  return response.data;
}

export async function signupRequest({ roomName, fullName, email, password }) {
  const response = await client.post("/auth/signup", {
    room_name: roomName,
    full_name: fullName,
    email,
    password,
  });

  return response.data;
}
