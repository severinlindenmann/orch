import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var details = false
    @State private var confirmSignOut = false
    @State private var signingOut = false
    @State private var requestingPermission = false

    var body: some View {
        ScrollViewReader { proxy in ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                ScreenHeading(title: "Settings.", subtitle: "Your connection, in one place.").padding(.top, 14)
                Eyebrow(text: "CONNECTION").padding(.top, 26).padding(.bottom, 12)
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 12) {
                        Text("◎").font(Theme.font(29)).foregroundStyle(Theme.brand)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Your workspace server").font(Theme.font(14, .semibold))
                            Text("●  Connected").font(Theme.font(11)).foregroundStyle(Theme.brand)
                        }
                    }
                    Rectangle().fill(Theme.border).frame(height: 1)
                    DisclosureGroup(isExpanded: $details) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Server: \(model.relayHost)")
                            Text("This phone: \(model.phoneName)")
                            Text("Access is managed by whoever invited you.")
                        }.font(Theme.font(11)).frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 10)
                    } label: { Text("Details").font(Theme.font(13)).frame(minHeight: 44) }
                    .foregroundStyle(Theme.muted)
                }.orchCard()
                HStack { Eyebrow(text: "YOUR WORKSPACES"); Spacer(); Eyebrow(text: "\(model.workspaces.count)") }
                    .padding(.top, 26).padding(.bottom, 12)
                VStack(spacing: 0) {
                    ForEach(model.workspaces) { workspace in
                        HStack {
                            Text(workspace.displayName)
                            Spacer()
                            Text(workspace.online ? "Online" : "Asleep").foregroundStyle(workspace.online ? Theme.brand : Theme.muted)
                                .font(Theme.font(12))
                        }.font(Theme.font(14)).padding(.vertical, 15)
                        if workspace.id != model.workspaces.last?.id { Rectangle().fill(Theme.border).frame(height: 1) }
                    }
                }.orchCard(padding: 16)
                Text("Need another workspace? Ask the person who invited you.")
                    .font(Theme.font(11)).foregroundStyle(Theme.muted).padding(.top, 12)
                Toggle("Notify me when I'm needed", isOn: Binding(get: { model.notificationsEnabled }, set: { enabled in
                    model.notificationsEnabled = enabled
                    if enabled {
                        requestingPermission = true
                        Task {
                            model.notificationsEnabled = await PushPermission.request()
                            requestingPermission = false
                        }
                    }
                })).font(Theme.font(14)).tint(Theme.brand).frame(minHeight: 44).padding(.vertical, 15)
                    .disabled(requestingPermission)
                    .overlay(alignment: .top) { Rectangle().fill(Theme.border).frame(height: 1) }
                    .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 1) }
                    .padding(.vertical, 26)
                Button("Sign out") { confirmSignOut = true }
                    .foregroundStyle(Theme.danger).frame(maxWidth: .infinity, minHeight: 48)
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Theme.border))
                if confirmSignOut {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Disconnect this phone? You will need a new invitation to connect again.").font(Theme.font(13))
                        Button("Sign out of this phone") {
                            signingOut = true
                            Task { await model.signOut(); signingOut = false }
                        }.foregroundStyle(Theme.danger).frame(maxWidth: .infinity, minHeight: 44)
                            .accessibilityIdentifier("signout-confirm")
                        Button("Cancel") { confirmSignOut = false }
                            .foregroundStyle(Theme.muted).frame(maxWidth: .infinity, minHeight: 44)
                    }.orchCard().disabled(signingOut).padding(.top, 12).id("signout-card")
                }
                ModelMessage().padding(.top, 12)
                Text("orch for iOS · \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0") (\(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"))").font(Theme.font(11)).foregroundStyle(Theme.muted)
                    .frame(maxWidth: .infinity).padding(.top, 12)
            }.padding(.horizontal, 23).padding(.top, 6).padding(.bottom, 20)
        }
        .onChange(of: confirmSignOut) { _, shown in if shown { withAnimation { proxy.scrollTo("signout-card", anchor: .bottom) } } }
        }
    }
}
