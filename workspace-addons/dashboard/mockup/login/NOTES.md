# Login with a token and the profile picker (ORCH-1035)

- `login.html` shows what a browser sees when it is not signed in: "Welcome", "Log in with your token", one field
  and Log in. Below it, for someone without a token (ORCH-1851): "No token yet?", ask the person who sent you this
  address for a private sign-in link or a token, how to use each, and last, small, the two commands for the person
  who runs the workspace (`orch dashboard open --print`: a sign-in link, once, 10 minutes; `orch dashboard token
  new`: a token, 30 days). `?state=wrong` shows a token that does not work (ask for a new one), `?state=link` a
  sign-in link that was already used or has ended (notice above the card; the heading turns to "Need a new link or
  token?"), `?state=picker` the "Who is using orch?" picker right after
  the login, and `?state=switch` the picker opened again from the "You:" menu (the current profile is marked).
- The picker lists the dashboard's people (big initials, colour from the name), "Add profile" and "Log out".
  The chosen profile acts for this browser only.
- Builders: `UI.doorLogin`, `UI.profilePicker` in the master `widgets.js` (gallery: "Login door", "Profile
  picker"). The product uses the same builders (`web/login.js`).
