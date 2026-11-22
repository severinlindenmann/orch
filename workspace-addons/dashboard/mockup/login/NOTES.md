# Login with a token and the profile picker (ORCH-1035)

- `login.html` shows what a browser sees when it is not signed in: "Welcome", "Log in with your token", one field
  and Log in. The token comes from `orch dashboard token new` on the workspace computer (30 days).
  `?state=wrong` shows a token that does not work, `?state=picker` the "Who is using orch?" picker right after
  the login, and `?state=switch` the picker opened again from the "You:" menu (the current profile is marked).
- The picker lists the dashboard's people (big initials, colour from the name), "Add profile" and "Log out".
  The chosen profile acts for this browser only.
- Builders: `UI.doorLogin`, `UI.profilePicker` in the master `widgets.js` (gallery: "Login door", "Profile
  picker"). The product uses the same builders (`web/login.js`).
