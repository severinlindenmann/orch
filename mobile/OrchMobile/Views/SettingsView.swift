import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var details = false
    @State private var confirmSignOut = false
    @State private var signingOut = false
    @State private var requestingPermission = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Brand().frame(height: 44).padding(.bottom, 28)
                ScreenHeading(title: "Settings.", subtitle: "Your connection, in one place.")
                Eyebrow(text: "CONNECTED RELAY").padding(.top, 26).padding(.bottom, 12)
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 12) {
                        Text("◎").font(.system(size: 29)).foregroundStyle(Theme.brand)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(model.relayHost).font(.system(size: 13, weight: .semibold))
                            Text("●  Connected").font(.system(size: 11)).foregroundStyle(Theme.brand)
                        }
                    }
                    Rectangle().fill(Theme.border).frame(height: 1)
                    DisclosureGroup(isExpanded: $details) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text(model.relayHost)
                            Text(model.phoneName)
                            Text("Access managed by your relay admin.")
                        }.font(.system(size: 11)).frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 10)
                    } label: { Text("Details").font(.system(size: 11)).frame(minHeight: 44) }
                    .foregroundStyle(Theme.muted)
                }.orchCard()
                HStack { Eyebrow(text: "YOUR WORKSPACES"); Spacer(); Eyebrow(text: "\(model.workspaces.count)") }
                    .padding(.top, 26).padding(.bottom, 12)
                VStack(spacing: 0) {
                    ForEach(model.workspaces) { workspace in
                        HStack {
                            Text(workspace.name)
                            Spacer()
                            Image(systemName: "checkmark").foregroundStyle(Theme.brand)
                        }.font(.system(size: 13)).padding(.vertical, 15)
                        if workspace.id != model.workspaces.last?.id { Rectangle().fill(Theme.border).frame(height: 1) }
                    }
                }.orchCard(padding: 16)
                Text("Need another workspace? Ask your relay admin.")
                    .font(.system(size: 11)).foregroundStyle(Theme.muted).padding(.top, 12)
                Toggle("Notifications", isOn: Binding(get: { model.notificationsEnabled }, set: { enabled in
                    model.notificationsEnabled = enabled
                    if enabled {
                        requestingPermission = true
                        Task {
                            model.notificationsEnabled = await PushPermission.request()
                            requestingPermission = false
                        }
                    }
                })).font(.system(size: 13)).frame(minHeight: 44).padding(.vertical, 15)
                    .disabled(requestingPermission)
                    .overlay(alignment: .top) { Rectangle().fill(Theme.border).frame(height: 1) }
                    .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 1) }
                    .padding(.vertical, 26)
                Button("Sign out") { confirmSignOut = true }
                    .foregroundStyle(Theme.danger).frame(maxWidth: .infinity, minHeight: 48)
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.border))
                if confirmSignOut {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Disconnect this phone from \(model.relayHost)?").font(.system(size: 13))
                        Button("Sign out of this phone") {
                            signingOut = true
                            Task { await model.signOut(); signingOut = false }
                        }.foregroundStyle(Theme.danger).frame(maxWidth: .infinity, minHeight: 44)
                            .accessibilityIdentifier("signout-confirm")
                        Button("Cancel") { confirmSignOut = false }
                            .foregroundStyle(Theme.muted).frame(maxWidth: .infinity, minHeight: 44)
                    }.orchCard().disabled(signingOut).padding(.top, 12)
                }
                ModelMessage().padding(.top, 12)
                Text("orch for iOS").font(.system(size: 11)).foregroundStyle(Theme.muted)
                    .frame(maxWidth: .infinity).padding(.top, 12)
            }.padding(.horizontal, 23).padding(.top, 6).padding(.bottom, 20)
        }
    }
}
