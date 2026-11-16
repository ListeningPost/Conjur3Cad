// Conjur3 Cloud Functions entrypoint.
import { setGlobalOptions } from "firebase-functions/v2";
import { syncPlatformAdmins } from "./lib/platform";

setGlobalOptions({ region: "us-central1", maxInstances: 10 });

// Keep config/platform (read by firestore.rules) in step with the
// PLATFORM_ADMIN_EMAILS env on every cold start (skipped while the Firebase
// CLI is only loading this module to discover functions at deploy time).
if (!process.env.FUNCTIONS_CONTROL_API) void syncPlatformAdmins();

export { createOrganization, grantSeats } from "./organizations";
export { claimMyKey, rotateMyKey, revokeMyKey, deleteMyKey } from "./seatKeys";
export { revokeKey } from "./keys";
export { setMemberRole, revokeMember, inviteMember } from "./members";
export {
  createOrgInvite,
  revokeOrgInvite,
  getOrgInvite,
  redeemOrgInvite,
} from "./orgInvites";
export { deleteSelf } from "./account";
export {
  createGuidedInvite,
  disableGuidedInvite,
  getGuidedInvite,
  redeemGuidedInvite,
} from "./guidedInvites";
export { onSubscriptionWrite } from "./billing";
export { devSeedSubscription } from "./dev";
