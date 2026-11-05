import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var details = false
    @State private var confirmSignOut = false
    @State private var signingOut = false
    @State private var requestingPermission = false

    private var statusText: String {
        switch model.connection {
        case .ok: "●  Connected" + (model.lastUpdatedText.map { " · " + $0.lowercased() } ?? "")
        case .unreachable: "●  Can't reach the server" + (model.lastUpdatedText.map { " · " + $0.lowercased() } ?? "")
        case .checking: "●  Checking…"
        }
    }
    private var statusColor: Color {
        switch model.connection { case .ok: Theme.brand; case .unreachable: Theme.danger; case .checking: Theme.muted }
    }

    @Environment(\.dynamicTypeSize) private var dynamicType  // re-evaluate fonts when text size changes (no view-identity reset)
    var body: some View {
        let _ = dynamicType
        ScrollViewReader { proxy in ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                ScreenHeading(title: "Settings.", subtitle: "Your connection, in one place.").padding(.top, 14)
                Eyebrow(text: "CONNECTION").padding(.top, 26).padding(.bottom, 12)
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 12) {
                        Text("◎").themeFont(29).foregroundStyle(Theme.brand)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Your workspace server").themeFont(14, .semibold)
                            Text(statusText).themeFont(12).foregroundStyle(statusColor)
                        }
                    }
                    Rectangle().fill(Theme.border).frame(height: 1)
                    DisclosureGroup(isExpanded: $details) {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Server: \(model.relayHost)")
                            Text("This phone: \(model.phoneName)")
                            Text("Access is managed by whoever invited you.")
                        }.themeFont(11).frame(maxWidth: .infinity, alignment: .leading).padding(.vertical, 10)
                    } label: { Text("Details").themeFont(13).frame(maxWidth: .infinity, minHeight: 44, alignment: .leading).contentShape(Rectangle()) }
                    .foregroundStyle(Theme.muted)
                }.orchCard()
                if !model.workspaces.isEmpty {
                HStack { Eyebrow(text: "YOUR WORKSPACES"); Spacer(); Eyebrow(text: "\(model.workspaces.count)") }
                    .padding(.top, 26).padding(.bottom, 12)
                VStack(spacing: 0) {
                    ForEach(model.workspaces) { workspace in
                        HStack {
                            Text(workspace.displayName)
                            Spacer()
                            Text(lastSeenText(workspace.lastSeen, online: workspace.online)).foregroundStyle(workspace.online ? Theme.brand : Theme.muted)
                                .themeFont(12)
                        }.themeFont(14).padding(.vertical, 15)
                        if workspace.id != model.workspaces.last?.id { Rectangle().fill(Theme.border).frame(height: 1) }
                    }
                }.orchCard(padding: 16)
                }
                Text("Need another workspace? Ask the person who invited you.")
                    .themeFont(11).foregroundStyle(Theme.muted).padding(.top, 12)
                Toggle("Notify me when I'm needed", isOn: Binding(get: { model.notificationsEnabled }, set: { enabled in
                    model.notificationsEnabled = enabled
                    if enabled {
                        requestingPermission = true
                        Task {
                            model.notificationsEnabled = await PushPermission.request()
                            requestingPermission = false
                        }
                    }
                })).themeFont(14).tint(Theme.brand).frame(minHeight: 44).padding(.vertical, 15)
                    .disabled(requestingPermission)
                    .accessibilityElement(children: .combine)
                    .overlay(alignment: .top) { Rectangle().fill(Theme.border).frame(height: 1) }
                    .overlay(alignment: .bottom) { Rectangle().fill(Theme.border).frame(height: 1) }
                    .padding(.vertical, 26)
                Button { confirmSignOut = true } label: { Text("Sign out") }
                    .buttonStyle(WideButtonStyle(color: Theme.danger, bordered: true))
                if confirmSignOut {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Disconnect this phone? You will need a new invitation to connect again.").themeFont(13)
                        Button {
                            signingOut = true
                            Task { await model.signOut(); signingOut = false }
                        } label: {
                            HStack(spacing: 8) { if signingOut { ProgressView().tint(Theme.danger) }; Text(signingOut ? "Signing out…" : "Sign out of this phone") }
                        }.buttonStyle(WideButtonStyle(color: Theme.danger))
                            .accessibilityIdentifier("signout-confirm")
                        Button { confirmSignOut = false } label: { Text("Cancel") }
                            .buttonStyle(WideButtonStyle(color: Theme.muted))
                    }.orchCard().disabled(signingOut).padding(.top, 12).id("signout-card")
                }
                ModelMessage().padding(.top, 12)
                Text("orch for iOS · \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0") (\(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"))").themeFont(11).foregroundStyle(Theme.muted)
                    .frame(maxWidth: .infinity).padding(.top, 12)
            }.padding(.horizontal, 23).padding(.top, 6).padding(.bottom, 20)
        }
        .onChange(of: confirmSignOut) { _, shown in if shown { if reduceMotion { proxy.scrollTo("signout-card", anchor: .bottom) } else { withAnimation(.easeOut(duration: 0.2)) { proxy.scrollTo("signout-card", anchor: .bottom) } } } }
        }
    }
}
