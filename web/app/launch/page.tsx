import { redirect } from "next/navigation";

/** The launcher moved into 02 STUDIO, where uploads actually reach the run. */
export default function LaunchRedirect() {
  redirect("/studio");
}
