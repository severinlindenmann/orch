import SwiftUI
import UIKit

struct OnboardingView: View {
    @Environment(AppModel.self) private var model
    @State private var showLink = false
    @State private var showScanner = false
    @State private var link = ""
    @State private var finishing = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Brand().frame(maxWidth: .infinity)
                if model.phase == .notifyStep {
                    ScreenHeading(title: "You're connected.", subtitle: model.pairedWorkspaces.count == 1 ? "1 workspace is ready." : "\(model.pairedWorkspaces.count) workspaces are ready.")
                        .padding(.top, 28)
                } else {
                    ScreenHeading(title: "Let's get connected.", subtitle: "Use your invitation to bring your workspaces along.").padding(.top, 28)
                }
                if model.phase == .notifyStep {
                    notificationStep
                } else {
                    invitationStep
                }
                ModelMessage()
            }.padding(.horizontal, 23).padding(.top, 12).padding(.bottom, 20)
        }
        .sheet(isPresented: $showLink) {
            VStack(alignment: .leading, spacing: 18) {
                Text("Paste invitation link").font(.headline)
                TextField("Paste invitation link", text: $link)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .keyboardType(.URL).padding(14).background(Theme.surface, in: RoundedRectangle(cornerRadius: 8))
                Button("Continue") {
                    model.openInvite(link); showLink = false
                }.buttonStyle(PrimaryButtonStyle()).disabled(link.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button("Close") { showLink = false }.frame(maxWidth: .infinity, minHeight: 44)
            }.padding(23).presentationDetents([.medium]).presentationBackground(Theme.bg)
        }
        .sheet(isPresented: $showScanner) {
            QRScannerView { code in model.openInvite(code); showScanner = false }
        }
    }

    @ViewBuilder private var invitationStep: some View {
        switch model.inviteState {
        case .none:
            VStack(spacing: 10) {
                Button { showScanner = true } label: { Label("Scan invitation QR code", systemImage: "qrcode.viewfinder") }
                    .buttonStyle(PrimaryButtonStyle())
                Button {
                    if let value = UIPasteboard.general.string, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                       (try? PairingLink(value)) != nil {
                        model.openInvite(value)
                    } else { showLink = true }
                } label: { Text("Paste invitation link") }.buttonStyle(SecondaryButtonStyle())
                Text("Ask the person who invited you for a link or QR code.").font(Theme.font(12))
                    .foregroundStyle(Theme.muted).frame(maxWidth: .infinity).padding(.top, 4)
                #if DEBUG
                Button("Try a demo") { model.openSampleInvite() }
                    .font(Theme.font(12)).foregroundStyle(Theme.muted)
                    .frame(maxWidth: .infinity, minHeight: 44).accessibilityIdentifier("sample-invite")
                #endif
            }
        case .found(let host):
            VStack(alignment: .leading, spacing: 12) {
                Text("Your workspace is ready").font(Theme.font(15, .semibold))
                Text("You were invited to connect this phone.").font(Theme.font(13)).foregroundStyle(Theme.muted)
                DisclosureGroup("Connection details") { Text(host).font(Theme.font(12)).frame(maxWidth: .infinity, alignment: .leading) }
                    .font(Theme.font(12)).foregroundStyle(Theme.muted)
            }.orchCard()
            Button("Connect this phone") {
                Task { await model.connect(phoneName: UIDevice.current.name) }
            }.buttonStyle(PrimaryButtonStyle())
        case .connecting:
            ProgressView("Connecting this phone…").frame(maxWidth: .infinity, minHeight: 80)
        }
    }

    private var notificationStep: some View {
        VStack(spacing: 18) {
            VStack(alignment: .leading, spacing: 12) {
                Text("Know when you're needed.").font(Theme.font(17, .semibold))
                Text("Get notified when your work needs an answer.")
                    .font(Theme.font(13)).foregroundStyle(Theme.muted)
                ForEach(model.pairedWorkspaces) { workspace in
                    Text(workspace.displayName).font(Theme.font(14)).padding(.vertical, 6)
                }
            }.orchCard()
            Button("Allow notifications") { finish(true) }.buttonStyle(PrimaryButtonStyle())
            Button("Not now") { finish(false) }.font(Theme.font(15)).foregroundStyle(Theme.muted).frame(maxWidth: .infinity, minHeight: 44)
            if finishing { ProgressView() }
        }.disabled(finishing)
    }

    private func finish(_ allowed: Bool) {
        finishing = true
        Task { await model.finishSetup(allowNotifications: allowed); finishing = false }
    }
}
