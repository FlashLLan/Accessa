import client from "./client";

export async function getReviewers() {
  const response = await client.get("/users/reviewers");
  return response.data;
}

export async function getMe() {
  const response = await client.get("/users/me");
  return response.data;
}