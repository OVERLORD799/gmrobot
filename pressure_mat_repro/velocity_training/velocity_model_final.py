import torch
import torch.nn as nn


class VelocityRegressor(nn.Module):
    def __init__(self, window_size, dropout=0.2):
        super(VelocityRegressor, self).__init__()

        in_channels = 1 if window_size == 0 else 2 * window_size

        self.conv_0 = nn.Sequential(
            nn.Conv2d(in_channels, 32, kernel_size=(3, 3), padding=1),
            nn.LeakyReLU(),
            nn.BatchNorm2d(32)
        )

        self.conv_1 = nn.Sequential(
            nn.Conv2d(32, 64, kernel_size=(3, 3), padding=1),
            nn.LeakyReLU(),
            nn.BatchNorm2d(64),
            nn.MaxPool2d(kernel_size=2)
        )

        self.conv_2 = nn.Sequential(
            nn.Conv2d(64, 128, kernel_size=(3, 3), padding=1),
            nn.LeakyReLU(),
            nn.BatchNorm2d(128)
        )

        self.conv_3 = nn.Sequential(
            nn.Conv2d(128, 256, kernel_size=(3, 3), padding=1),
            nn.LeakyReLU(),
            nn.BatchNorm2d(256),
            nn.MaxPool2d(kernel_size=2)
        )

        self.conv_4 = nn.Sequential(
            nn.Conv2d(256, 512, kernel_size=(3, 3), padding=1),
            nn.LeakyReLU(),
            nn.BatchNorm2d(512)
        )

        self.conv_5 = nn.Sequential(
            nn.Conv2d(512, 1024, kernel_size=(5, 5)),
            nn.LeakyReLU(),
            nn.BatchNorm2d(1024)
        )

        self.conv_6 = nn.Sequential(
            nn.Conv2d(1024, 1024, kernel_size=(3, 3), padding=1),
            nn.LeakyReLU(),
            nn.BatchNorm2d(1024),
            nn.MaxPool2d(kernel_size=2)
        )

        self.head = nn.Sequential(
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
            nn.Linear(1024, 512),
            nn.LeakyReLU(),
            nn.Dropout(p=dropout),
            nn.Linear(512, 128),
            nn.LeakyReLU(),
            nn.Linear(128, 3)
        )

    def forward(self, input_tensor):
        output = self.conv_0(input_tensor)
        output = self.conv_1(output)
        output = self.conv_2(output)
        output = self.conv_3(output)
        output = self.conv_4(output)
        output = self.conv_5(output)
        output = self.conv_6(output)
        output = self.head(output)
        return output


def masked_mse_loss(pred, target, valid_mask):
    errors = (pred - target) ** 2
    errors = torch.sum(errors, dim=1)
    valid = valid_mask.float()
    denom = torch.clamp(torch.sum(valid), min=1.0)
    return torch.sum(errors * valid) / denom


def masked_mae_loss(pred, target, valid_mask):
    errors = torch.abs(pred - target)
    errors = torch.sum(errors, dim=1)
    valid = valid_mask.float()
    denom = torch.clamp(torch.sum(valid), min=1.0)
    return torch.sum(errors * valid) / denom